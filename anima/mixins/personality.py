"""
PersonalityMixin —— Phase 3 人格向量 + 3B 记忆情绪染色
============================================
v0.8.0 从 main.py 抽出：# ==================== Phase 3: 人格向量系统 ====================; # ==================== Phase 3B: 记忆情绪染色 ====================

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


class PersonalityMixin:
    """Phase 3 人格向量 + 3B 记忆情绪染色 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _default_personality_vector(self) -> dict:
        """默认 5 维人格向量（0-1）"""
        return {
            "expressiveness": 0.5,          # 表达欲：想表达/分享的冲动
            "sensitivity": 0.5,             # 敏感度：对外界刺激的反应强度
            "boundary_permeability": 0.5,   # 边界通透：愿意让他人靠近/了解的程度
            "order_sense": 0.5,             # 秩序感：对规律、结构、控制的需求
            "relationship_gravity": 0.5,    # 关系引力：被他人吸引、投入关系的倾向
        }

    def _get_personality_vector(self) -> dict:
        """获取当前人格向量（优先内存，其次 state）"""
        if hasattr(self, "_personality_vector") and self._personality_vector:
            return self._personality_vector.copy()
        state = self._load_state()
        pv = state.get("personality_vector")
        if isinstance(pv, dict) and len(pv) == 5:
            self._personality_vector = pv
            return pv.copy()
        pv = self._default_personality_vector()
        self._personality_vector = pv
        self._save_personality_vector(pv)
        return pv.copy()

    def _save_personality_vector(self, pv: dict):
        """持久化人格向量（原子读-改-写）"""
        def _update(state: dict):
            state["personality_vector"] = pv
        self._atomic_update_state(_update)
        self._personality_vector = pv

    def _analyze_monologue_for_personality(self, monologue: str) -> dict:
        """从独白文本中提取 5 维人格信号，返回 delta 建议（-0.3 ~ +0.3）"""
        text = monologue.lower()
        deltas = {k: 0.0 for k in self._default_personality_vector().keys()}

        # 表达欲信号
        expr_pos = ["我想说", "忍不住", "一直想", "藏着", "憋着", "终于可以", "表达", "分享", "吐露"]
        expr_neg = ["不想说", "沉默", "闭口", "保密", "不说", "忍住"]
        deltas["expressiveness"] = 0.12 * sum(kw in text for kw in expr_pos) - 0.08 * sum(kw in text for kw in expr_neg)

        # 敏感度信号
        sens_pos = ["敏感", "触动", "心疼", "在意", "震动", "共鸣", "心被", "细腻"]
        sens_neg = ["麻木", "无感", "不在意", "迟钝"]
        deltas["sensitivity"] = 0.10 * sum(kw in text for kw in sens_pos) - 0.08 * sum(kw in text for kw in sens_neg)

        # 边界通透信号
        bound_pos = ["告诉你", "分享给你", "没关系", "可以让你知道", "靠近", "敞开", "透明"]
        bound_neg = ["我的事", "别问", "隐私", "界限", "不让你", "封闭", "不靠近"]
        deltas["boundary_permeability"] = 0.10 * sum(kw in text for kw in bound_pos) - 0.08 * sum(kw in text for kw in bound_neg)

        # 秩序感信号
        order_pos = ["理清楚", "规律", "顺序", "计划", "结构", "整理", "控制", "稳定"]
        order_neg = ["混乱", "无序", "随便", "放任", "失控"]
        deltas["order_sense"] = 0.10 * sum(kw in text for kw in order_pos) - 0.08 * sum(kw in text for kw in order_neg)

        # 关系引力信号
        rel_pos = ["想你", "喜欢你", "靠近你", "你重要", "吸引", "舍不得", "好想", "关系"]
        rel_neg = ["远离", "疏远", "不重要", "无所谓", "切断"]
        deltas["relationship_gravity"] = 0.12 * sum(kw in text for kw in rel_pos) - 0.08 * sum(kw in text for kw in rel_neg)

        # 裁剪范围
        for k in deltas:
            deltas[k] = max(-0.35, min(0.35, deltas[k]))
        return deltas

    def _adjust_personality_from_monologue(self, monologue: str):
        """EMA 平滑微调人格向量（沉淀后调用）"""
        if not monologue or len(monologue) < 8:
            return
        pv = self._get_personality_vector()
        deltas = self._analyze_monologue_for_personality(monologue)
        alpha = 0.12  # 缓慢演化
        changed = False
        for dim, delta in deltas.items():
            if abs(delta) < 0.01:
                continue
            old = pv[dim]
            # delta 是建议偏移，基准 0.5 + delta 作为目标方向
            target = max(0.0, min(1.0, 0.5 + delta))
            pv[dim] = (1 - alpha) * old + alpha * target
            if abs(pv[dim] - old) > 0.005:
                changed = True
        if changed:
            self._save_personality_vector(pv)
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima][Phase3] 人格向量微调: { {k: round(v,2) for k,v in pv.items()} }")

    def _get_personality_injection_text(self) -> str:
        """生成注入上下文的人格向量描述"""
        pv = self._get_personality_vector()
        labels = {
            "expressiveness": "表达欲",
            "sensitivity": "敏感度",
            "boundary_permeability": "边界通透",
            "order_sense": "秩序感",
            "relationship_gravity": "关系引力",
        }
        parts = [f"{labels[k]}:{pv[k]:.1f}" for k in labels]
        return "人格向量（" + " / ".join(parts) + "）"


    def _estimate_memory_valence(self, text: str) -> float:
        """v0.7.0: 委托给 anima.valence"""
        return _ext_estimate_valence(text)

    def _rerank_memories_by_emotion(self, memories: list, current_emotion: float) -> list:
        """v0.7.0: 委托给 anima.valence"""
        return _ext_rerank_memories(memories, current_emotion)
