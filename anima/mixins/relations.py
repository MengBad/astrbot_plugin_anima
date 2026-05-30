"""
RelationsMixin —— Phase 3C 跨关系传播
================================
v0.8.0 从 main.py 抽出：# ==================== Phase 3C: 跨关系传播 ====================

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


class RelationsMixin:
    """Phase 3C 跨关系传播 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _get_sender_user_id(self, event: AstrMessageEvent) -> str:
        """提取当前发送者数字 ID 字符串"""
        try:
            if hasattr(event, "message_obj") and event.message_obj:
                uid = getattr(event.message_obj.sender, "user_id", None)
                if uid:
                    return str(uid)
        except Exception as e:
            logger.debug(f"[Anima] 获取 sender uid 失败: {e}")
        return ""

    def _update_user_low_emotion_streak(self, uid: str, score: float):
        """更新用户低情绪连续计数（< 阈值记为低）。原子读-改-写。
        v0.9.6：阈值与触发门槛改为可配，修复"日常闲聊每轮触发跨关系传播"的性能黑洞。
        此前硬编码 score<0.35（闲聊本就 0.0-0.25 全中）+ 连续 3 次，过于频繁。"""
        if not uid:
            return
        low_threshold = float(self.config.get("cross_relation_low_emotion_threshold", 0.2))
        streak_threshold = int(self.config.get("cross_relation_streak_threshold", 5))
        triggered_propagate = {"v": False}

        def _update(state: dict):
            streaks = state.get("user_low_emotion_streaks", {})
            if score < low_threshold:
                streaks[uid] = streaks.get(uid, 0) + 1
            else:
                streaks[uid] = 0
            # 清理：只保留最近有记录的，最多 30 个
            if len(streaks) > 30:
                # 丢弃 streak==0 的旧条目
                active = {k: v for k, v in streaks.items() if v > 0}
                if len(active) < 25:
                    streaks = active
            state["user_low_emotion_streaks"] = streaks
            if streaks.get(uid, 0) >= streak_threshold:
                triggered_propagate["v"] = True

        self._atomic_update_state(_update)

        if triggered_propagate["v"]:
            # 触发跨关系传播（不阻塞当前沉淀）
            try:
                asyncio.create_task(self._propagate_cross_relation_scar(uid))
            except Exception as e:
                logger.debug(f"[Anima] 触发跨关系传播失败: {e}")

    def _are_relations_similar(self, desc1: str, desc2: str) -> bool:
        """简单判断两个 social_graph 描述是否指向相似关系类型"""
        if not desc1 or not desc2:
            return False
        kws = ["朋友", "亲密", "信任", "喜欢", "重要", "爱", "家人", "亲近", "疏远", "冷淡", "讨厌", "陌生"]
        shared = 0
        d1, d2 = desc1.lower(), desc2.lower()
        for k in kws:
            if k in d1 and k in d2:
                shared += 1
        if shared >= 1:
            return True
        # 词重叠兜底
        w1 = set(re.findall(r'[\u4e00-\u9fff]{2,}', desc1))
        w2 = set(re.findall(r'[\u4e00-\u9fff]{2,}', desc2))
        return len(w1 & w2) >= 2

    async def _propagate_cross_relation_scar(self, low_uid: str):
        """跨关系传播：低情绪连续 → 相似关系用户的伤痕敏感度微调"""
        try:
            wv = self._read_worldview()
            sg = wv.get("social_graph", {})
            if not sg or len(sg) < 2:
                return
            low_desc = sg.get(low_uid, "")
            candidates = []
            for uid, desc in sg.items():
                if uid == low_uid:
                    continue
                if self._are_relations_similar(low_desc, desc):
                    candidates.append((uid, desc))
            if not candidates:
                # 回退：随机挑一个其他用户
                others = [u for u in sg if u != low_uid]
                if others:
                    candidates = [(others[0], sg[others[0]])]
            if not candidates:
                return

            target_uid, _ = candidates[0]
            # 微调伤痕：低情绪往往放大 rejection / abandonment / trust_breach
            scars = self._read_scar_dimensions()
            dim = "rejection"
            if "信任" in low_desc or "背叛" in low_desc:
                dim = "trust_breach"
            elif "离开" in low_desc or "不要" in low_desc:
                dim = "abandonment"
            if dim not in scars:
                scars[dim] = {"count": 1, "sensitivity": 1.0, "last_triggered": ""}
            old_s = scars[dim].get("sensitivity", 1.0)
            scars[dim]["sensitivity"] = min(3.0, old_s + 0.04)  # 微小传播 0.04
            scars[dim]["last_triggered"] = datetime.now().isoformat()
            self._write_scar_dimensions(scars)

            # 记录传播历史（原子读-改-写）
            entry = {
                "ts": datetime.now().isoformat(),
                "source_user": low_uid,
                "target_similar": target_uid,
                "scar_dim": dim,
                "delta": 0.04,
            }
            def _update(state: dict):
                hist = state.get("cross_propagations", [])
                hist.append(entry)
                state["cross_propagations"] = hist[-30:]
            self._atomic_update_state(_update)

            logger.info(f"[Anima][Phase3] 跨关系传播触发: {low_uid} 连续低情绪 → {target_uid} 的 {dim} 敏感度 +0.04")
        except Exception as e:
            logger.debug(f"[Anima][Phase3] 跨关系传播异常: {e}")
