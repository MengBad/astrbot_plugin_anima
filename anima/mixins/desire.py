"""
DesireMixin —— 模块一 欲望系统
=======================
v0.8.0 从 main.py 抽出：# ==================== 模块一：欲望系统 ====================

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


class DesireMixin:
    """模块一 欲望系统 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。

    v0.8.0：所有 desire 加 target_umo 字段，按 unified_msg_origin 隔离，
    防止 A 群产生的执念被 B 群事件触发释放。

    数据格式（向后兼容）：旧 desire 没有 target_umo 字段，视为"通用兜底"，
    任何 umo 都可见但优先级低于精确匹配。
    """

    @staticmethod
    def _get_event_umo(event) -> str:
        """安全提取 unified_msg_origin。失败返回空串。"""
        if event is None:
            return ""
        try:
            return getattr(event, "unified_msg_origin", "") or ""
        except Exception:
            return ""

    def _filter_desires_for_umo(self, desires: list, umo: str) -> list:
        """筛选当前 umo 可见的 desires。
        - target_umo 完全匹配：可见
        - target_umo 缺失或为空（旧数据/突变执念）：通用，可见
        - target_umo 是其他 umo：不可见
        """
        if not umo:
            # 没有 event 时（如反刍流程），返回所有 desires
            return list(desires)
        return [
            d for d in desires
            if not d.get("target_umo") or d.get("target_umo") == umo
        ]

    def _read_desires(self) -> list:
        """读取欲望队列（不做 umo 过滤，原始读）"""
        return self._read_json(self.desires_path, default=[])

    def _read_desires_for_event(self, event) -> list:
        """按当前 event umo 过滤后的欲望队列。所有需要"按对话上下文行动"的路径都该用这个。"""
        umo = self._get_event_umo(event)
        return self._filter_desires_for_umo(self._read_desires(), umo)

    def _write_desires(self, desires: list):
        """写入欲望队列"""
        self._write_json(self.desires_path, desires)

    def _decay_desires(self):
        """欲望衰减：每次调用 intensity *= 0.95，低于 0.1 的删除"""
        desires = self._read_desires()
        if not desires:
            return
        updated = []
        for d in desires:
            d["intensity"] = d.get("intensity", 0.5) * 0.95
            if d["intensity"] >= 0.1 and not d.get("satisfied", False):
                updated.append(d)
        self._write_desires(updated)

    def _check_desire_satisfaction(self, text: str, event=None):
        """检查对话内容是否满足某个欲望（语义匹配优先，回退关键词匹配）。
        v0.8.0：仅匹配当前 umo 可见的欲望，避免跨群误满足。
        """
        all_desires = self._read_desires()
        if not all_desires:
            return
        umo = self._get_event_umo(event)
        changed = False
        for d in all_desires:
            if d.get("satisfied"):
                continue
            # 仅检查属于当前 umo 或通用（无 target_umo）的欲望
            d_umo = d.get("target_umo", "")
            if d_umo and umo and d_umo != umo:
                continue
            content = d.get("content", "")
            keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content)
            if any(kw in text for kw in keywords):
                d["satisfied"] = True
                changed = True
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 欲望已满足(关键词): {content[:50]}")
        if changed:
            self._write_desires([d for d in all_desires if not d.get("satisfied")])

    async def _check_desire_satisfaction_semantic(self, text: str, event=None):
        """语义匹配版本的欲望满足检查（需要向量记忆可用）。
        v0.8.0：按 umo 隔离。
        """
        if not self._kb_available:
            self._check_desire_satisfaction(text, event)
            return
        all_desires = self._read_desires()
        if not all_desires:
            return
        umo = self._get_event_umo(event)
        changed = False
        for d in all_desires:
            if d.get("satisfied"):
                continue
            d_umo = d.get("target_umo", "")
            if d_umo and umo and d_umo != umo:
                continue
            content = d.get("content", "")
            try:
                # v0.8.8: 走 _kb_call_with_retry（database is locked 退避重试）
                #         + wait_for 超时，避免裸调在 kb.db 高并发锁时阻塞整个沉淀
                result = await asyncio.wait_for(
                    self._kb_call_with_retry(
                        lambda: self.context.kb_manager.retrieve(
                            query=content,
                            kb_names=["anima_memory"],
                            top_m_final=3,
                        ),
                        op_name="欲望满足检索",
                    ),
                    timeout=15.0,
                )
                if result and result.get("results"):
                    for r in result["results"]:
                        score = r.get("score", 0)
                        if score > 0.7:
                            d["satisfied"] = True
                            changed = True
                            if self.config.get("log_level") == "debug":
                                logger.debug(f"[Anima] 欲望已满足(语义 {score:.2f}): {content[:50]}")
                            break
            except Exception:
                keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content)
                if any(kw in text for kw in keywords):
                    d["satisfied"] = True
                    changed = True
        if changed:
            self._write_desires([d for d in all_desires if not d.get("satisfied")])

    async def _maybe_generate_desire(self, event: AstrMessageEvent, sylanne_state: str, response_text: str):
        """沉淀后判断是否产生新欲望。

        v0.8.3：写入前过滤跟 response_text（bot 刚刚回复）语义相似的欲望，
        避免主动发言重复 bot 已经说过的话。
        """
        if not self.config.get("desire_enabled", False):
            return
        logger.debug("[Anima] 尝试生成欲望...")
        if not sylanne_state:
            return

        desires = self._read_desires()
        max_queue = self.config.get("desire_max_queue", 5)
        if len(desires) >= max_queue:
            return

        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            prompt = (
                "根据当前关系状态和对话内容，这个角色此刻有没有产生什么"
                "想做的事、想知道的事、或想对某人说的话？\n"
                "如果有，用一句话描述。如果没有，只回复'无'。\n\n"
                f"关系状态：{sylanne_state[:200]}\n"
                f"对话回复：{response_text[:200]}\n"
                f"用户消息：{(event.message_str or '')[:200]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if self._is_rejected(result):
                    return
                if result and result != "无" and len(result) > 2:
                    # v0.8.3 防线 A：跟 bot 刚刚的回复对比，太相似就丢弃
                    # 因为这种欲望往往是"想问 X" 但 bot 在回复里已经问过 X 了
                    if await self._is_desire_already_expressed(result, response_text, event):
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 欲望已在回复中表达，跳过: {result[:40]}")
                        return
                    sender_id = ""
                    if hasattr(event, "message_obj") and event.message_obj:
                        sender_id = getattr(event.message_obj.sender, "user_id", "")
                    new_desire = {
                        "id": f"desire_{int(time.time())}",
                        "content": result,
                        "source": "relationship",
                        "intensity": 0.7,
                        "created_at": datetime.now().isoformat(),
                        "target_user": sender_id,
                        "target_umo": self._get_event_umo(event),  # v0.8.0: 跨群隔离
                        "satisfied": False,
                    }
                    desires.append(new_desire)
                    self._write_desires(desires)
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 新欲望: {result[:50]}")
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 欲望生成失败: {e}")

    async def _is_desire_already_expressed(self, desire_text: str, response_text: str, event=None) -> bool:
        """v0.8.3: 判断这个欲望是否已经在 bot 的回复里被表达过。

        策略：embedding 余弦相似度优先（复用 v0.7.0 的 _embed_one / _cosine_similarity），
        失败时回退到 Jaccard。阈值 0.45 命中即视为重复。

        v0.8.4: 默认阈值提到 0.50，让 B 防线更严。
        """
        if not desire_text or not response_text:
            return False
        threshold = float(self.config.get("desire_dedup_threshold", 0.50))
        # 优先 embedding（如果配置了 embedding_provider_id）
        try:
            if hasattr(self, "_embed_one") and hasattr(self, "_cosine_similarity"):
                v1 = await self._embed_one(desire_text)
                v2 = await self._embed_one(response_text)
                if v1 and v2:
                    sim = self._cosine_similarity(v1, v2)
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 欲望去重 cosine={sim:.3f} vs threshold={threshold}")
                    return sim >= threshold
        except Exception:
            pass
        # 回退 Jaccard
        try:
            tokens_a = _ext_text_token_set(desire_text)
            tokens_b = _ext_text_token_set(response_text)
            if not tokens_a or not tokens_b:
                return False
            sim = _ext_jaccard(tokens_a, tokens_b)
            return sim >= threshold
        except Exception:
            return False

    async def _is_topic_relevant_to_context(self, topic_text: str, context_text: str) -> bool:
        """v0.8.4: 判断"打算说的话题"是否跟"当前对话上下文"相关。

        防线 D：拦截幻觉话题。
        - 跟 _is_desire_already_expressed 是反向的：B 拦"太相似"，D 拦"太无关"
        - 当 topic_text 跟 context_text 相似度 < 阈值时，视为 LLM 幻觉出来的、
          跟当前对话毫无关联的话题 → 返回 False
        - 上下文为空或 topic 为空时返回 True（不拦），避免冷启动误伤

        阈值分路（v0.8.4）：
        - cosine 路径用 topic_relevance_threshold（默认 0.40）—— 语义模型分数高
          v0.8.4 hotfix: 生产观察 "ASMR音声" vs "笨蛋+bot回复" 算出 0.366，
          0.20 太松拦不住，提到 0.40
        - Jaccard fallback 用 topic_relevance_threshold_jaccard（默认 0.05）
          —— 中文 ngram 让 Jaccard 分母被撑得很大，0.20 会误伤正常对话；
          0.05 在生产观察样本上能区分"完全无关"和"弱相关"

        生产观察案例：群里只聊过"@bot 笨蛋"三次，bot 突然问"这部作品是 ASMR 还是音声呀？"
        → topic vs context 的 cosine=0.366，应被拦下。
        """
        if not topic_text:
            return True
        if not context_text or len(context_text.strip()) < 2:
            # 没有上下文参考时不拦（冷启动）
            return True
        # 优先 embedding
        try:
            if hasattr(self, "_embed_one") and hasattr(self, "_cosine_similarity"):
                v1 = await self._embed_one(topic_text)
                v2 = await self._embed_one(context_text)
                if v1 and v2:
                    sim = self._cosine_similarity(v1, v2)
                    threshold = float(self.config.get("topic_relevance_threshold", 0.40))
                    if self.config.get("log_level") == "debug":
                        logger.debug(
                            f"[Anima] 话题关联性 cosine={sim:.3f} vs threshold={threshold}"
                        )
                    return sim >= threshold
        except Exception:
            pass
        # 回退 Jaccard：阈值更宽松，因为中文 ngram 让 Jaccard 普遍偏低
        try:
            tokens_a = _ext_text_token_set(topic_text)
            tokens_b = _ext_text_token_set(context_text)
            if not tokens_a or not tokens_b:
                return True  # 分不出 token 就不拦
            sim = _ext_jaccard(tokens_a, tokens_b)
            jaccard_threshold = float(
                self.config.get("topic_relevance_threshold_jaccard", 0.05)
            )
            if self.config.get("log_level") == "debug":
                logger.debug(
                    f"[Anima] 话题关联性 jaccard={sim:.3f} vs threshold={jaccard_threshold}"
                )
            return sim >= jaccard_threshold
        except Exception:
            return True  # 出错时不拦，宁可放过不可误伤

    def _build_recent_context_text(self, event) -> str:
        """v0.8.4: 拼出"最近对话上下文"参考文本，用于话题关联性检查。

        组合来源：
        1. 当前用户消息 (event.message_str)
        2. 最近 1 条 bot 回复 (self._outgoing_by_umo[umo][1])

        足够判断"当前对话主题"是什么。返回空串表示没有任何上下文可参考。
        """
        parts = []
        try:
            if event is not None:
                user_text = getattr(event, "message_str", "") or ""
                if user_text:
                    parts.append(user_text[:300])
        except Exception:
            pass
        try:
            umo = self._get_event_umo(event)
            if umo and hasattr(self, "_outgoing_by_umo"):
                record = self._outgoing_by_umo.get(umo) or self._outgoing_by_umo.get("_default_")
                if record and record[1]:
                    parts.append(record[1][:300])
        except Exception:
            pass
        return " ".join(parts).strip()

    async def _evaluate_desire_from_monologue(self, monologue: str):
        """从独白/反刍结果中提取潜在欲望"""
        desires = self._read_desires()
        max_queue = self.config.get("desire_max_queue", 5)
        if len(desires) >= max_queue:
            return

        try:
            providers = self.context.get_all_providers()
            if not providers:
                return
            internal = self.config.get("internal_provider_id", "")
            provider_id = internal if internal else providers[0].meta().id

            prompt = (
                "以下是一个角色的内心独白。从中提取它此刻想做的事、想知道的事、"
                "或想对某人说的话。如果有，用一句话描述。如果没有，只回复'无'。\n\n"
                f"独白：{monologue[:300]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                result = llm_resp.completion_text.strip()
                if result and result != "无" and len(result) > 2:
                    # v0.8.9：源头过滤。从内心独白提取的"欲望"如果本身就是煽情自白
                    # （港湾/深渊/拥抱太阳之类），不该入队 —— 它没有对外行动指向，
                    # 一旦被 stance_propagation 拿去润色就会变成跟当前对话无关的深情
                    # 发言泄漏出去。这类独白只该留在 self_notes，不该变成对外欲望。
                    if hasattr(self, "_looks_like_inner_monologue") and self._looks_like_inner_monologue(result):
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 提取的欲望疑似煽情自白，不入队: {result[:50]}")
                        return
                    desires.append({
                        "id": f"desire_{int(time.time())}",
                        "content": result,
                        "source": "self",
                        "intensity": 0.6,
                        "created_at": datetime.now().isoformat(),
                        "target_user": "",
                        "target_umo": "",  # v0.8.0: 独白/反刍产生的欲望是通用的（每个会话都可见）
                        "satisfied": False,
                    })

                    # Phase 6+ B: 高强度欲望自动触发自主研究（角色主动想学东西）
                    if desires[-1]["intensity"] >= 0.75:
                        asyncio.create_task(self._initiate_self_directed_research(
                            "高强度欲望驱动",
                            f"我有一个强烈的欲望：{result[:80]}。我可能需要发展新能力来实现它。",
                            force=False
                        ))
                    self._write_desires(desires)
                    logger.debug(f"[Anima] 反刍产生欲望: {result[:50]}")
        except Exception as e:
            logger.debug(f"[Anima] 反刍欲望提取失败: {e}")

    def _get_active_desires_text(self, event=None) -> str:
        """获取高强度欲望的注入文本。
        v0.8.0：仅返回当前 umo 可见的欲望（target_umo 匹配或为空）。
        当 event=None（如反刍流程）时返回所有 desires。
        """
        if not self.config.get("desire_enabled", False):
            return ""
        desires = self._read_desires_for_event(event)
        active = [d for d in desires if d.get("intensity", 0) > 0.3]
        if not active:
            return ""
        # v0.8.8: 用 .get 避免历史/外部写入的 desire 缺 content 字段时 KeyError
        # （此方法在 on_llm_request 注入路径上，外层无 try 兜底，抛错会打断主对话注入）
        lines = [
            f"此刻内心隐约想着：{c}"
            for d in active[:3]
            if (c := d.get("content", "").strip())
        ]
        return "\n".join(lines)
