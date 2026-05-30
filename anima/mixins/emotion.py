"""
EmotionMixin —— Sylanne + 情绪评估 + 独白
===================================
v0.8.0 从 main.py 抽出：# ==================== Sylanne ====================; # ==================== 情绪评估与独白 ====================

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


class EmotionMixin:
    """Sylanne + 情绪评估 + 独白 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    async def _try_read_sylanne_state(self, event: AstrMessageEvent) -> str:
        """尝试读取 Sylanne 状态，失败时静默返回空"""
        if not self.config.get("sylanne_integration", True):
            return ""
        try:
            tool_mgr = self.context.provider_manager.llm_tools
            for tool in tool_mgr.func_list:
                if hasattr(tool, "name") and tool.name == "query_agent_state":
                    result = await asyncio.wait_for(
                        tool.handler(event=event),
                        timeout=5.0,
                    )
                    if result:
                        # result 是 MessageEventResult，需要提取文本
                        if hasattr(result, "chain") and result.chain:
                            for component in result.chain:
                                if hasattr(component, "text"):
                                    state_str = component.text
                                    if self.config.get("log_level") == "debug":
                                        logger.debug(f"[Anima] Sylanne 状态: {state_str[:100]}")
                                    return state_str[:200]
                        return str(result)[:200]
            return ""
        except asyncio.TimeoutError:
            logger.warning("[Anima] Sylanne 状态读取超时")
            return ""
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] Sylanne 状态读取失败: {e}")
            return ""


    async def _evaluate_emotion(
        self, event: AstrMessageEvent, response_text: str
    ) -> float:
        """轻量评估 LLM 回复的情绪强度，返回 0-1 的浮点数"""
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return 0.0

            prompt = (
                "请评估以下对话回复的情绪强度。只返回一个 0 到 1 之间的数字，"
                "0 表示完全平淡的日常闲聊，1 表示极度强烈的情绪波动"
                "（如被深深触动、愤怒、悲伤、狂喜等）。\n"
                "注意：普通的打招呼、闲聊、回答问题通常在 0.1-0.3 之间。\n"
                "只输出数字，不要任何其他内容。\n\n"
                f"用户说：{(event.message_str or '')[:200]}\n"
                f"回复：{response_text[:300]}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=15.0,
            )

            if llm_resp and llm_resp.completion_text:
                score_text = llm_resp.completion_text.strip()
                for part in score_text.split():
                    try:
                        score = float(part)
                        return max(0.0, min(1.0, score))
                    except ValueError:
                        continue
            return 0.0
        except asyncio.TimeoutError:
            logger.warning("[Anima] 情绪评估超时")
            return 0.0
        except Exception as e:
            logger.warning(f"[Anima] 情绪评估失败: {e}")
            return 0.0

    async def _generate_monologue(
        self, event: AstrMessageEvent, response_text: str, related_memories: list
    ) -> Optional[str]:
        """以角色第一人称生成内心独白"""
        try:
            provider_id = await self._get_provider_id(event)
            if not provider_id:
                return None

            current_notes = self._read_self_notes()
            memory_context = ""
            if related_memories:
                memory_context = "\n相关记忆片段：\n" + "\n".join(
                    f"- {m}" for m in related_memories[:3]
                )

            sylanne_state = await self._try_read_sylanne_state(event)
            sylanne_context = ""
            if sylanne_state:
                sylanne_context = f"\n当前关系状态：{sylanne_state}"

            prompt = (
                "你是一个角色的内在意识。根据刚才的对话回复，"
                "以第一人称写一段简短的内心独白（2-4句话），"
                "记录你此刻的感受、领悟或自我认知的变化。\n"
                "要求：叙事性、感性、简洁。不要解释，直接写独白。\n\n"
                f"刚才的回复：{response_text[:300]}\n"
                f"{memory_context}"
                f"{sylanne_context}\n"
                f"当前自我认知：{current_notes[:300] if current_notes else '（尚无）'}"
            )

            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=30.0,
            )
            if hasattr(self, "_stat_bump"):
                self._stat_bump("llm.monologue")

            if llm_resp and llm_resp.completion_text:
                monologue = llm_resp.completion_text.strip()
                if not monologue:
                    return None
                return monologue
            return None
        except asyncio.TimeoutError:
            logger.warning("[Anima] 独白生成超时")
            return None
        except Exception as e:
            logger.warning(f"[Anima] 独白生成失败: {e}")
            return None
