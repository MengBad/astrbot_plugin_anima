"""
ForgettingMixin —— 模块四 遗忘机制
===========================
v0.8.0 从 main.py 抽出：# ==================== 模块四：遗忘机制 ====================

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


class ForgettingMixin:
    """模块四 遗忘机制 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _apply_forgetting(self, notes: str) -> str:
        """v0.7.0: 委托给 anima.forgetting"""
        if not self.config.get("forgetting_enabled", False):
            return notes
        halflife_days = self.config.get("forgetting_halflife_days", 14)
        return _ext_apply_forgetting(notes, halflife_days)

    def _awaken_memories(self, related_memories: list):
        """唤醒被检索命中的旧记忆：将匹配条目的时间戳更新为当前时间"""
        if not self.config.get("forgetting_enabled", False):
            return
        if not related_memories:
            return

        notes = self._read_self_notes()
        if not notes:
            return

        blocks = notes.split("\n---\n")
        changed = False
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for i, block in enumerate(blocks):
            # 检查这个 block 是否与检索到的记忆匹配（取前 50 字符做子串匹配）
            for mem in related_memories:
                # 记忆片段的前 50 字符如果出现在 block 中，认为命中
                snippet = mem[:50] if len(mem) > 50 else mem
                if snippet and snippet in block:
                    # 替换时间戳为当前时间
                    match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]', block)
                    if match:
                        old_ts = match.group(1)
                        blocks[i] = block.replace(f"[{old_ts}]", f"[{now_str}]", 1)
                        changed = True
                        if self.config.get("log_level") == "debug":
                            logger.debug(f"[Anima] 唤醒记忆: {snippet[:30]}...")
                    break  # 一个 block 只唤醒一次

        if changed:
            self._write_self_notes("\n---\n".join(blocks))
