"""
FeedbackMixin —— Phase 2C 反馈闭环
==============================
v0.8.0 从 main.py 抽出：# ==================== Phase 2C：反馈闭环 ====================

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


class FeedbackMixin:
    """Phase 2C 反馈闭环 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _record_outgoing(self, event: AstrMessageEvent, content: str):
        """记录角色的一次发言，启动观察窗口（按 umo 隔离）"""
        umo = getattr(event, "unified_msg_origin", "") or "_default_"
        self._outgoing_by_umo[umo] = (time.time(), content[:200])
        # 兜底：避免无限增长（保留最近 50 个 umo）
        if len(self._outgoing_by_umo) > 50:
            # 按 ts 升序，丢最早的
            sorted_items = sorted(self._outgoing_by_umo.items(), key=lambda x: x[1][0])
            self._outgoing_by_umo = dict(sorted_items[-50:])

    @staticmethod
    def _text_token_set(text: str) -> set:
        """v0.7.0: 委托给 anima.similarity"""
        return _ext_text_token_set(text)

    @staticmethod
    def _jaccard_similarity(a: set, b: set) -> float:
        """v0.7.0: 委托给 anima.similarity"""
        return _ext_jaccard(a, b)

    @staticmethod
    def _cosine_similarity(v1: list, v2: list) -> float:
        """v0.7.0: 委托给 anima.similarity"""
        return _ext_cosine(v1, v2)

    async def _embed_one(self, text: str) -> Optional[list]:
        """v0.7.0: 调用 embedding provider 把 text 转为向量。失败返回 None。"""
        embedding_id = self.config.get("embedding_provider_id", "")
        if not embedding_id:
            return None
        try:
            providers = self.context.get_all_embedding_providers()
            target = None
            for p in providers:
                meta = p.meta() if callable(getattr(p, "meta", None)) else None
                pid = getattr(meta, "id", "") if meta else ""
                if pid == embedding_id:
                    target = p
                    break
            if not target:
                # 回退：用 provider_registry 按 id 搜索（兼容 meta() 不可用的版本）
                from ..sylanne_alpha.provider_registry import find_provider_by_id
                target = find_provider_by_id(self.context, embedding_id, kinds=("embedding",))
            if not target:
                return None
            # 不同 AstrBot 版本的 embedding 接口名可能不同，按常见命名兜底尝试
            for method_name in ("get_embedding", "embed", "embed_text", "create_embedding"):
                method = getattr(target, method_name, None)
                if callable(method):
                    result = method(text[:500])
                    if asyncio.iscoroutine(result):
                        result = await asyncio.wait_for(result, timeout=8.0)
                    # 期望返回 [float, ...] 或 [[float, ...]]
                    if isinstance(result, list) and result:
                        if isinstance(result[0], (int, float)):
                            return list(result)
                        if isinstance(result[0], list):
                            return list(result[0])
                    return None
            return None
        except Exception as e:
            logger.debug(f"[Anima] embedding 调用失败: {e}")
            return None

    async def _check_embedding_availability(self) -> bool:
        """v0.9.6: 探测 embedding provider 是否真正可用（返回非空向量）。
        用于启动自检，让"靠猜方法名调用→静默降级 Jaccard"的情况可被察觉。"""
        if not self.config.get("embedding_provider_id"):
            return False
        try:
            v = await self._embed_one("健康检查")
            return bool(v) and isinstance(v, list) and len(v) > 0
        except Exception:
            return False

    async def _evaluate_feedback(self, event: AstrMessageEvent) -> str:
        """v0.7.0: 评估用户对角色上次发言的反馈：accepted/ignored/rejected/none。
        每个 umo 各自维护一个观察窗口。

        语义判定优先级：
        1) 明确否定词（rejected）— 不变
        2) 用 embedding 算余弦相似度（若 embedding_provider 可用）
        3) 兜底：ngram + Jaccard 相似度（替代旧的"≥2 关键词重叠"硬阈值）
        阈值：相似度 ≥ 0.30 视为 accepted；< 0.10 视为 ignored；中间区段也算 accepted（保守不误判 ignored）。
        """
        umo = getattr(event, "unified_msg_origin", "") or "_default_"
        record = self._outgoing_by_umo.get(umo)
        if not record:
            return "none"
        last_ts, last_content = record
        if not last_content:
            return "none"
        elapsed = time.time() - last_ts
        if elapsed > 300:  # 超过 5 分钟，窗口过期
            self._outgoing_by_umo.pop(umo, None)
            return "none"

        user_text = event.message_str or ""
        if not user_text:
            return "none"

        # 1) 明确否定词
        reject_words = ["不对", "错了", "闭嘴", "别说了", "滚", "放屁", "胡说"]
        if any(w in user_text for w in reject_words):
            return "rejected"

        # 2) 优先尝试 embedding 余弦相似度
        sim = -1.0
        try:
            v1 = await self._embed_one(last_content)
            v2 = await self._embed_one(user_text)
            if v1 and v2:
                sim = self._cosine_similarity(v1, v2)
                if self.config.get("log_level") == "debug":
                    logger.debug(f"[Anima] 反馈相似度（embedding）: {sim:.3f}")
        except Exception as e:
            logger.debug(f"[Anima] embedding 比对失败，回退 Jaccard: {e}")

        # 3) 兜底：ngram + Jaccard
        if sim < 0:
            sim = self._jaccard_similarity(
                self._text_token_set(last_content),
                self._text_token_set(user_text),
            )
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 反馈相似度（jaccard）: {sim:.3f}")

        # 阈值（v0.9.6 可配）：accepted/ignored 之间判 none（中性），不再保守判 accepted
        acc_t = float(self.config.get("feedback_accepted_threshold", 0.45))
        ign_t = float(self.config.get("feedback_ignored_threshold", 0.15))
        if sim >= acc_t:
            return "accepted"
        if sim < ign_t:
            return "ignored"
        # 中间区段：判 none（此前误判 accepted，导致日常对话延续被大量当成正反馈）
        return "none"

    def _process_feedback(self, feedback: str, event: AstrMessageEvent):
        """根据反馈信号调整系统状态"""
        if feedback == "none":
            return

        umo = getattr(event, "unified_msg_origin", "") or "_default_"
        record = self._outgoing_by_umo.get(umo)
        last_content = record[1] if record else ""

        if feedback == "accepted":
            # 增强该类话题的欲望权重（不做额外操作，自然演化）
            logger.debug("[Anima] 反馈: accepted")
        elif feedback == "ignored":
            # 角色被忽略 → 转入压抑话题
            if last_content:
                self._add_suppressed_topic(
                    topic=f"想说但被忽略了：{last_content[:80]}",
                    source="ignored",
                )
                logger.debug("[Anima] 反馈: ignored → 转入压抑话题")
        elif feedback == "rejected":
            # 被拒绝 → 可能产生新伤痕
            self._add_scar("rejection")
            logger.debug("[Anima] 反馈: rejected → 伤痕加深")

        # 清空该 umo 的观察窗口
        self._outgoing_by_umo.pop(umo, None)
