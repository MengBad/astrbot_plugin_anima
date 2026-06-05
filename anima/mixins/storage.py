"""
StorageMixin —— 知识库 + 文件读写
==========================
v0.8.0 从 main.py 抽出：# ==================== 知识库 ====================; # ==================== 文件读写 ====================

依赖宿主类（AnimaPlugin）提供 self.* 状态字段（self.config / self.context / self.data_dir / self._io_lock 等）。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import LLMResponse, ProviderRequest

from ..filters import is_rejected as _ext_is_rejected, is_sensitive as _ext_is_sensitive
from ..similarity import (
    text_token_set as _ext_text_token_set,
    jaccard_similarity as _ext_jaccard,
    cosine_similarity as _ext_cosine,
)
from ..forgetting import apply_forgetting as _ext_apply_forgetting
from ..valence import (
    estimate_memory_valence as _ext_estimate_valence,
    rerank_memories_by_emotion as _ext_rerank_memories,
)


class StorageMixin:
    """知识库 + 文件读写 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    async def _ensure_kb(self) -> bool:
        """懒加载：确保知识库已创建。返回知识库是否可用。

        v1.2.2: 不再在尝试前缓存失败——仅在成功后标记 _kb_initialized，
        失败时设置重试冷却（60 秒），避免 provider 系统未就绪时永久降级。
        """
        if self._kb_initialized:
            return self._kb_available

        # 冷却期内不重试，避免频繁调用
        now = time.time()
        if hasattr(self, "_kb_retry_after") and now < self._kb_retry_after:
            return False

        embedding_id = self.config.get("embedding_provider_id", "")
        if not embedding_id:
            if self.config.get("log_level") == "debug":
                logger.debug("[Anima] 未配置 embedding_provider_id，向量记忆功能禁用")
            return False

        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if not kb:
                await self.context.kb_manager.create_kb(
                    kb_name="anima_memory",
                    embedding_provider_id=embedding_id,
                )
                logger.info("[Anima] 知识库 anima_memory 创建成功")
            self._kb_initialized = True
            self._kb_available = True
            return True
        except Exception as e:
            logger.warning(f"[Anima] 知识库初始化失败（60 秒后重试）: {e}")
            self._kb_available = False
            self._kb_retry_after = now + 60
            return False

    @staticmethod
    def _is_db_locked_error(exc: Exception) -> bool:
        """判断异常是否为 SQLite 'database is locked' 瞬时锁。

        v0.8.6：kb.db 被 AstrBot LTM / Sylanne / Anima 多方并发读写，
        高并发下 SQLite 单写锁会抛 OperationalError('database is locked')。
        这是毫秒级瞬时锁，退避重试基本能过。其它异常不在此列。
        """
        return "database is locked" in str(exc).lower()

    async def _kb_call_with_retry(self, coro_factory, op_name: str, max_retries: int = 6):
        """对 kb 调用做 'database is locked' 退避重试的通用包装。

        v0.8.6：kb.db 是多插件共享的 SQLite，高并发瞬时写锁会让单次调用失败。
        重构升级：最大重试 6 次，使用递增的指数退避延迟序列，并配合随机抖动（Jitter），
        错开多方并发的写盘周期。

        - coro_factory: 一个 0 参可调用对象，每次重试都重新调用它生成新的协程
          （协程不能复用，必须每次重新构造）。
        - op_name: 用于日志的操作名（如 "记忆存储" / "记忆检索"）。
        - 非锁异常立即抛出，由调用方原有的 try/except 处理（保持行为不变）。
        """
        # 指数退避延迟序列（秒）
        backoffs = [0.1, 0.3, 0.6, 1.2, 2.0, 3.0]
        attempt = 0
        while True:
            try:
                return await coro_factory()
            except Exception as e:
                if not self._is_db_locked_error(e):
                    raise  # 非锁错误，交给调用方原有处理
                if attempt >= max_retries:
                    logger.warning(
                        f"[Anima] {op_name}遇到 database is locked，"
                        f"已重试 {max_retries} 次仍失败: {e}"
                    )
                    raise
                base = backoffs[min(attempt, len(backoffs) - 1)]
                # 随机抖动（Jitter）逻辑：实际延迟时间 = 基准退避时间 + random.uniform(0, 基准时间 * 0.5)
                delay = base + random.uniform(0, base * 0.5)
                if self.config.get("log_level") == "debug":
                    logger.debug(
                        f"[Anima] {op_name}遇到 database is locked，"
                        f"第 {attempt + 1} 次退避 {delay:.3f}s 后重试"
                    )
                await asyncio.sleep(delay)
                attempt += 1

    async def _store_memory(self, text: str, event: Optional[AstrMessageEvent] = None, role: str = "in"):
        """将文本存入内存缓冲区，触发后台批处理写入。

        - 缓冲窗口：3 秒防抖动延迟
        - 批次上限：15 条/次
        - 内存保护：当缓冲区 >= 100 条时强制紧急写入（Emergency Flush）
        """
        if not await self._ensure_kb():
            return
        # v0.8.2: 拒答短语过滤 —— 命中就跳过，不污染知识库
        if self._is_rejected(text):
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 跳过拒答内容入库: {text[:50]}")
            return
        # v0.8.5: prompt 注入 / 越狱文本过滤 —— 命中就跳过，不污染知识库
        if self._is_injection(text):
            logger.warning(f"[Anima] 跳过疑似注入/越狱内容入库: {text[:60]}")
            return
        # v0.8.7: 框架/运行时错误文本过滤 —— 命中就跳过
        if self._is_error_artifact(text):
            logger.warning(f"[Anima] 跳过框架错误文本入库: {text[:60]}")
            return
        # 按用户限流（v0.8.5: 用户消息与 bot 回复独立限流，互不挤占）
        interval = self.config.get("memory_store_interval", 30)
        user_id = "default"
        if event and hasattr(event, "get_sender_id"):
            try:
                user_id = str(event.get_sender_id())
            except Exception:
                pass
        store_key = f"{user_id}:{role}"
        now = time.time()
        if now - self._last_store_time.get(store_key, 0) < interval:
            return
        self._last_store_time[store_key] = now
        # 敏感内容过滤
        if self._is_sensitive(text):
            return
        try:
            # v0.8.7: 剥掉反引号/代码块，避免格式污染 + 自我强化模仿
            clean_text = self._strip_markdown(text)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            text_with_time = f"[{timestamp}] {clean_text}"

            # 懒加载初始化缓冲区和触发器（以防未被主类 __init__ 初始化）
            if not hasattr(self, "_write_buffer"):
                self._write_buffer = []
            if not hasattr(self, "_worker_trigger"):
                self._worker_trigger = asyncio.Event()

            # 将文本送入内存 Buffer，完全非阻塞
            self._write_buffer.append(text_with_time)

            # 内存溢出保护：如果积压的任务超过 100 条，立即强制唤醒 worker 进行 emergency flush
            if len(self._write_buffer) >= 100:
                self._worker_trigger.set()
            # 正常积攒到防抖动阈值（如 10 条）直接唤醒 worker 执行写入
            elif len(self._write_buffer) >= 10:
                self._worker_trigger.set()
            # 零启动触发：加入首条数据时，唤醒以启动 3 秒窗口定时器
            elif len(self._write_buffer) == 1:
                self._worker_trigger.set()

            if hasattr(self, "_stat_bump"):
                self._stat_bump(f"store.{role}")
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 记忆已推入缓冲队列 ({len(self._write_buffer)} 条): {text_with_time[:50]}...")
        except Exception as e:
            logger.warning(f"[Anima] 向量存储入队失败: {e}")

    async def _batch_write_worker(self):
        """SQLite 记忆批量写入的后台守护协程。"""
        # 兜底初始化
        if not hasattr(self, "_write_buffer"):
            self._write_buffer = []
        if not hasattr(self, "_worker_trigger"):
            self._worker_trigger = asyncio.Event()

        while True:
            try:
                # 1. 缓冲区为空：无限期挂起等待新任务注入
                if not self._write_buffer:
                    self._worker_trigger.clear()
                    await self._worker_trigger.wait()
                elif len(self._write_buffer) < 10:
                    # 2. 缓冲数量少于 10 条：进入防抖动等待窗口（3秒），等待更多数据聚合
                    try:
                        self._worker_trigger.clear()
                        await asyncio.wait_for(self._worker_trigger.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        pass  # 3秒缓冲窗口到期，进行写入

                # 3. 提取批次上限 15 条进行批量执行
                batch = self._write_buffer[:15]
                self._write_buffer = self._write_buffer[15:]

                if batch:
                    await self._flush_batch(batch)

            except asyncio.CancelledError:
                # 4. 插件卸载或 Bot 退出时，安全清空并写入所有剩余记忆（Flush）
                await self._flush_all_remaining()
                raise
            except Exception as e:
                logger.error(f"[Anima] SQLite 记忆批处理写入任务发生异常: {e}")
                await asyncio.sleep(1.0)  # 避免异常情况下的死循环

    async def _flush_batch(self, batch: list[str]):
        """执行批次写入操作，采用 _kb_call_with_retry 承载 SQLite 重试。"""
        if not batch:
            return

        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if not kb:
                logger.warning("[Anima] 知识库未就绪，批次存储已跳过")
                return

            await self._kb_call_with_retry(
                lambda: kb.upload_document(
                    file_name=f"memory_batch_{int(time.time())}_{random.randint(1000, 9999)}",
                    file_content=None,
                    file_type="txt",
                    pre_chunked_text=batch,
                ),
                op_name="批量记忆存储",
            )
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 批次记忆写入成功，写入数: {len(batch)}")
        except Exception as e:
            logger.error(f"[Anima] 批次记忆写入彻底失败: {e}")

    async def _flush_all_remaining(self):
        """强制写入当前内存中积压的所有记忆条目。"""
        # 兜底检查
        if not hasattr(self, "_write_buffer") or not self._write_buffer:
            return
        
        logger.info(f"[Anima] 正在清空并强制写入剩余的 {len(self._write_buffer)} 条记忆...")
        while self._write_buffer:
            batch = self._write_buffer[:15]
            self._write_buffer = self._write_buffer[15:]
            if batch:
                try:
                    await self._flush_batch(batch)
                except Exception as e:
                    logger.error(f"[Anima] 写入剩余记忆子批次失败: {e}")
                    break

    async def _query_memory(self, query: str, n_results: int = 3) -> list:
        """从知识库检索相关记忆。

        v0.8.2 防线 2：返回前过滤掉历史已经污染的拒答条目（兼容已有数据）。
        因为 v0.8.2 之前知识库里可能已经存了 N 条 "I can't discuss that"，
        即使 _store_memory 不再写新拒答了，旧的还会被检索回来。
        """
        if not await self._ensure_kb():
            return []
        try:
            # 多取一些再过滤（防止过滤掉太多导致返回不够）
            over_fetch = max(n_results * 3, 10)
            result = await self._kb_call_with_retry(
                lambda: self.context.kb_manager.retrieve(
                    query=query,
                    kb_names=["anima_memory"],
                    top_m_final=over_fetch,
                ),
                op_name="记忆检索",
            )
            if result and result.get("results"):
                filtered = []
                for r in result["results"]:
                    content = r.get("content", "")
                    # 防线 2：过滤拒答 + 敏感内容
                    if self._is_rejected(content):
                        continue
                    if self._is_sensitive(content):
                        continue
                    # v0.8.5: 过滤注入/越狱文本（旧污染软删除 —— 删不掉就不让它进 prompt）
                    if self._is_injection(content):
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 检索跳过注入污染: {content[:60]}")
                        continue
                    # v0.8.7: 过滤框架错误文本（旧污染软删除）
                    if self._is_error_artifact(content):
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 检索跳过错误文本污染: {content[:60]}")
                        continue
                    # v0.8.7: 剥掉反引号/代码块（清掉旧污染记忆里的 markdown 标记，
                    #         避免带反引号的历史发言被注入后让模型继续模仿）
                    content = self._strip_markdown(content)
                    filtered.append(content)
                    if len(filtered) >= n_results:
                        break
                return filtered
            return []
        except Exception as e:
            logger.warning(f"[Anima] 向量检索失败: {e}")
            return []


    def _read_self_notes(self) -> str:
        """读取 self_notes.md 内容"""
        if not os.path.exists(self.self_notes_path):
            return ""
        try:
            with open(self.self_notes_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            logger.warning(f"[Anima] 读取 self_notes 失败: {e}")
            return ""

    def _write_self_notes(self, content: str):
        """写入 self_notes.md（持锁）"""
        try:
            with self._io_lock:
                with open(self.self_notes_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except OSError as e:
            logger.warning(f"[Anima] 写入 self_notes 失败: {e}")

    def _append_self_notes(self, entry: str):
        """追加内容到 self_notes.md（持锁）"""
        try:
            with self._io_lock:
                with open(self.self_notes_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n---\n{entry}")
        except OSError as e:
            logger.warning(f"[Anima] 追加 self_notes 失败: {e}")

    def _append_evolution_log(self, trigger: str, old_summary: str, new_content: str):
        """追加演化日志（持锁，单行 JSONL 写入应整体原子化）"""
        # 敏感内容过滤
        if self._is_sensitive(old_summary):
            old_summary = "[已过滤敏感内容]"
        if self._is_sensitive(new_content):
            new_content = "[已过滤敏感内容]"
        record = {
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "old_summary": old_summary[:200],
            "new_content": new_content[:500],
        }
        try:
            with self._io_lock:
                with open(self.evolution_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"[Anima] 写入 evolution_log 失败: {e}")

    def _read_evolution_log(self, n: int = 5) -> list:
        """读取最近 n 条演化日志"""
        if not os.path.exists(self.evolution_log_path):
            return []
        lines = []
        with open(self.evolution_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return lines[-n:]
