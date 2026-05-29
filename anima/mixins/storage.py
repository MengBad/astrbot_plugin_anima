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
        """懒加载：确保知识库已创建。返回知识库是否可用。"""
        if self._kb_initialized:
            return self._kb_available

        embedding_id = self.config.get("embedding_provider_id", "")
        if not embedding_id:
            if self.config.get("log_level") == "debug":
                logger.debug("[Anima] 未配置 embedding_provider_id，向量记忆功能禁用")
            return False

        self._kb_initialized = True
        try:
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if not kb:
                await self.context.kb_manager.create_kb(
                    kb_name="anima_memory",
                    embedding_provider_id=embedding_id,
                )
                logger.info("[Anima] 知识库 anima_memory 创建成功")
            self._kb_available = True
            return True
        except Exception as e:
            logger.warning(f"[Anima] 知识库初始化失败: {e}")
            self._kb_initialized = False
            self._kb_available = False
            return False

    async def _store_memory(self, text: str, event: Optional[AstrMessageEvent] = None, role: str = "in"):
        """将文本存入知识库。

        v0.8.2 防线 1：拒答内容（"I can't discuss that" / "对此我无法" 等）不入库，
        避免历史拒答被检索回来 prime 模型继续拒答（自我强化循环）。

        v0.8.5 防线：prompt 注入 / 越狱文本不入库。

        v0.8.5 限流修复：限流 key 按 (user_id, role) 区分，避免同一轮对话里
        用户消息先存入后刷新时间戳、紧接着把 bot 回复挤掉的问题（导致 bot
        "记不住自己说过的话"）。role="in" 为用户消息，role="out" 为 bot 回复。
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
            kb = await self.context.kb_manager.get_kb_by_name("anima_memory")
            if kb:
                # 加时间戳，让 bot 知道这条记忆是什么时候的
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                text_with_time = f"[{timestamp}] {text}"
                await kb.upload_document(
                    file_name=f"memory_{int(time.time())}",
                    file_content=None,
                    file_type="txt",
                    pre_chunked_text=[text_with_time],
                )
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 存储记忆: {text_with_time[:50]}...")
        except Exception as e:
            logger.warning(f"[Anima] 向量存储失败: {e}")

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
            result = await self.context.kb_manager.retrieve(
                query=query,
                kb_names=["anima_memory"],
                top_m_final=over_fetch,
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
