"""
CompressionMixin —— 笔记压缩
========================
v0.8.0 从 main.py 抽出：# ==================== 压缩 ====================

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


class CompressionMixin:
    """笔记压缩 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    async def _compress_notes(self, event: AstrMessageEvent):
        """当 self_notes 超过最大长度时，调用 LLM 压缩"""
        try:
            notes = self._read_self_notes()
            max_len = self.config.get("notes_max_length", 5000)
            if len(notes) <= max_len:
                return

            logger.info("[Anima] self_notes 超出长度限制，开始压缩...")

            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return

            # 如果启用遗忘机制，压缩时告知 LLM 可以丢弃极度模糊的记忆
            forgetting_hint = ""
            if self.config.get("forgetting_enabled", False):
                forgetting_hint = (
                    "\n标注为'记忆极度模糊'的条目可以丢弃。"
                    "标注为'记忆模糊'的条目可以大幅精简。"
                )

            prompt = (
                "以下是一个角色的自我认知笔记，内容过长需要压缩。\n"
                "请保留最重要的自我认知、核心记忆和关键转变，"
                "用第一人称重写为更精炼的版本（不超过原文的一半长度）。\n"
                f"保持叙事性和感性的风格。{forgetting_hint}\n\n"
                f"原文：\n{notes}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=60.0,
            )

            if llm_resp and llm_resp.completion_text:
                compressed = llm_resp.completion_text.strip()
                old_summary = notes[:200]
                self._write_self_notes(compressed)
                self.config["self_notes_editor"] = compressed
                self._last_synced_editor_content = compressed
                self.config.save_config()
                self._append_evolution_log(
                    trigger="compression",
                    old_summary=old_summary,
                    new_content=f"[压缩] {compressed[:200]}",
                )
                logger.info("[Anima] self_notes 压缩完成")
        except asyncio.TimeoutError:
            logger.warning("[Anima] 笔记压缩超时")
        except Exception as e:
            logger.warning(f"[Anima] 笔记压缩失败: {e}")
