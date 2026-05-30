"""
TimeSenseMixin —— 模块三 时间感
=========================
v0.8.0 从 main.py 抽出：# ==================== 模块三：时间感系统 ====================

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


class TimeSenseMixin:
    """模块三 时间感 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _read_time_sense(self, umo: str = "") -> dict:
        """读取时间感数据。v0.9.8：按 umo 会话隔离（不存在则回退全局文件）。"""
        return self._read_session_json(
            umo, "time_sense.json", self.time_sense_path,
            default=lambda: {
                "last_interaction": {},
                "interaction_frequency": {},
                "session_start": None,
                "total_messages_today": 0,
            },
        )

    def _write_time_sense(self, data: dict, umo: str = ""):
        """写入时间感数据。v0.9.8：只写该 umo 的会话文件。"""
        self._write_session_json(umo, "time_sense.json", data)

    def _update_time_sense(self, event: AstrMessageEvent):
        """每条消息进来时更新时间感"""
        if not self.config.get("time_sense_enabled", False):
            return

        ts = self._read_time_sense(self._get_event_umo(event))
        now = datetime.now()
        now_str = now.isoformat()

        # 获取发送者 ID
        sender_id = ""
        if hasattr(event, "message_obj") and event.message_obj:
            sender_id = getattr(event.message_obj.sender, "user_id", "")
        if not sender_id:
            sender_id = "unknown"

        # 更新 last_interaction
        if "last_interaction" not in ts:
            ts["last_interaction"] = {}
        ts["last_interaction"][sender_id] = now_str

        # 更新 interaction_frequency（滑动窗口：存储时间戳列表，只保留 24h 内的）
        if "interaction_timestamps" not in ts:
            ts["interaction_timestamps"] = {}
        if sender_id not in ts["interaction_timestamps"]:
            ts["interaction_timestamps"][sender_id] = []
        ts["interaction_timestamps"][sender_id].append(now_str)
        # 清理超过 24h 的时间戳
        cutoff = (now - timedelta(hours=24)).isoformat()
        ts["interaction_timestamps"][sender_id] = [
            t for t in ts["interaction_timestamps"][sender_id] if t > cutoff
        ]
        # 同步 interaction_frequency 为当前窗口内的计数
        if "interaction_frequency" not in ts:
            ts["interaction_frequency"] = {}
        ts["interaction_frequency"][sender_id] = len(ts["interaction_timestamps"][sender_id])

        # session_start：如果为空或超过 4 小时，重置
        if not ts.get("session_start"):
            ts["session_start"] = now_str
        else:
            try:
                session_start = datetime.fromisoformat(ts["session_start"])
                if (now - session_start) > timedelta(hours=4):
                    ts["session_start"] = now_str
                    ts["total_messages_today"] = 0
            except (ValueError, TypeError):
                ts["session_start"] = now_str

        ts["total_messages_today"] = ts.get("total_messages_today", 0) + 1

        self._write_time_sense(ts, self._get_event_umo(event))

    def _get_time_sense_text(self, event: AstrMessageEvent) -> str:
        """获取时间感注入文本。

        v0.7.0: 之前会对 worldview.social_graph 里每个超过 24h 没说话的 user_id
        都触发一次自主研究 + 注入一行文本——单条用户消息可能批量产出 10+ 条 absence
        触发，被节流后变成大量"研究跳过"日志。

        现在改为：从所有久违用户里挑选最多 2 个最重要的（互动频次高 & 最久未见）触发，
        其余仅做内部计数，不再触发研究、不再注入"很久没见到 X 了"。
        """
        if not self.config.get("time_sense_enabled", False):
            return ""

        ts = self._read_time_sense(self._get_event_umo(event))
        now = datetime.now()
        parts = []

        # 收集所有久违用户的（uid, 已缺席天数, 互动频次）
        last_interactions = ts.get("last_interaction", {})
        freq_map = ts.get("interaction_frequency", {})
        absent_candidates = []  # [(uid, days_absent, frequency)]
        for user_id, last_time_str in last_interactions.items():
            try:
                last_time = datetime.fromisoformat(last_time_str)
                hours = (now - last_time).total_seconds() / 3600.0
                if hours >= 24:
                    days = hours / 24.0
                    freq = int(freq_map.get(user_id, 0))
                    absent_candidates.append((user_id, days, freq))
            except (ValueError, TypeError):
                continue

        # 排序：先按 frequency 降序（重要的人优先），然后按 days_absent 降序（久违的优先）
        absent_candidates.sort(key=lambda x: (-x[2], -x[1]))

        # v0.7.0: 仅取最重要的 2 个，且只为他们触发研究/注入文本
        top_absent = absent_candidates[:2]
        for user_id, days, _freq in top_absent:
            parts.append(f"好像很久没见到 {user_id} 了")
            # 长时间缺失（>3 天）→ 触发自主研究（节流由 _initiate_self_directed_research 内部处理）
            if days > 3:
                asyncio.create_task(self._initiate_self_directed_research(
                    f"长时间未见 {user_id}",
                    "我好久没和这个人互动了。我需要发展更好的方式来重新连接或表达思念。",
                    force=False
                ))

        # 检查当前会话是否持续超过 2 小时
        session_start_str = ts.get("session_start")
        if session_start_str:
            try:
                session_start = datetime.fromisoformat(session_start_str)
                if (now - session_start) > timedelta(hours=2):
                    parts.append("今晚聊了很久了")
            except (ValueError, TypeError):
                pass

        return "\n".join(parts[:3])  # 最多注入 3 条
