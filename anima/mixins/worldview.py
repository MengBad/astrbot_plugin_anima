"""
WorldviewMixin —— 模块二 世界观
=========================
v0.8.0 从 main.py 抽出：# ==================== 模块二：世界观系统 ====================

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


class WorldviewMixin:
    """模块二 世界观 mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _read_worldview(self) -> dict:
        """读取世界观"""
        return self._read_json(self.worldview_path, default={})

    def _write_worldview(self, data: dict):
        """写入世界观"""
        self._write_json(self.worldview_path, data)

    async def _maybe_update_worldview(self, event: AstrMessageEvent, force: bool = False):
        """每 20 次沉淀触发一次世界观更新。

        v0.8.1：social_graph 膨胀后整个 prompt 太长导致 LLM 超时。
        修复：传给 LLM 时仅注入"最近活跃的 N 个用户 + 当前发送者"画像，
        其余 social_graph 条目在合并写回阶段保留。
        """
        if not self.config.get("worldview_enabled", False):
            return
        logger.debug(f"[Anima] 检查世界观更新... (沉淀计数: {self._sediment_count})")
        if not force and self._sediment_count % 20 != 0:
            return

        try:
            worldview_prov = self.config.get("worldview_provider_id", "")
            provider_id = await self._get_provider_id(event, prefer=worldview_prov)
            if not provider_id:
                return

            current_wv = self._read_worldview()
            recent_notes = self._read_self_notes()[-1500:]

            # 获取当前发送者 ID
            sender_id = ""
            if hasattr(event, "message_obj") and event.message_obj:
                sender_id = str(getattr(event.message_obj.sender, "user_id", ""))

            # v0.8.1: 截断 social_graph 后再传 LLM，避免 prompt 爆炸
            full_graph = current_wv.get("social_graph", {})
            graph_cap = int(self.config.get("worldview_graph_inject_cap", 8))
            wv_for_prompt = dict(current_wv)
            if len(full_graph) > graph_cap:
                # 简单策略：保留当前发送者 + 最后 N 个 key（dict 在 Python 3.7+ 保序）
                keep_keys = []
                if sender_id and sender_id in full_graph:
                    keep_keys.append(sender_id)
                # 反向取最近的 N 个，去掉已加入的发送者
                for k in reversed(list(full_graph.keys())):
                    if k not in keep_keys:
                        keep_keys.append(k)
                    if len(keep_keys) >= graph_cap:
                        break
                wv_for_prompt["social_graph"] = {k: full_graph[k] for k in keep_keys}
                wv_for_prompt["_social_graph_truncated"] = (
                    f"（仅显示 {len(keep_keys)}/{len(full_graph)} 条最相关画像）"
                )

            prompt = (
                "你正在帮助一个 AI 聊天角色整理对群聊环境的认知。"
                "以下是角色的内心独白记录，请从中提取对群环境的客观认知。\n"
                "根据这些信息，更新角色对这个群的理解。"
                "包括：environment（环境氛围）、social_graph（群友画像，用 user_id 做 key）、"
                "norms（群内规范）、my_position（角色的位置）。\n"
                "social_graph 的 key 必须使用用户的数字 ID（如 1562290139），不要用名字。"
                "如果不知道某人的 ID，可以用描述性名称作为临时 key，但优先使用 ID。\n"
                f"当前消息发送者 ID：{sender_id}\n"
                "输出纯 JSON 格式，不要 markdown 代码块。\n\n"
                f"已有世界观（节选）：{json.dumps(wv_for_prompt, ensure_ascii=False)}\n\n"
                f"最近的内心独白：{recent_notes}"
            )

            logger.debug(f"[Anima] 世界观更新 prompt 长度: {len(prompt)}")

            # v0.8.1: timeout 30s → 60s，留出大 prompt 处理时间
            llm_resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                ),
                timeout=float(self.config.get("worldview_update_timeout", 60.0)),
            )
            if hasattr(self, "_stat_bump"):
                self._stat_bump("llm.worldview")

            if llm_resp and llm_resp.completion_text:
                text = llm_resp.completion_text.strip()
                if self._is_rejected(text):
                    return
                # 尝试提取 JSON
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                try:
                    new_wv = json.loads(text)
                    # v0.8.1: 合并写回 —— LLM 只看了截断版的 social_graph，
                    # 所以要把它返回的 social_graph 跟原始 full_graph 合并，
                    # 不要让没传给 LLM 的旧画像被丢掉
                    if "social_graph" in new_wv and isinstance(new_wv["social_graph"], dict):
                        merged = dict(full_graph)
                        merged.update(new_wv["social_graph"])
                        new_wv["social_graph"] = merged
                    new_wv.pop("_social_graph_truncated", None)
                    new_wv["last_updated"] = datetime.now().isoformat()
                    self._write_worldview(new_wv)
                    logger.info(
                        f"[Anima] 世界观已更新（social_graph: {len(new_wv.get('social_graph', {}))} 条）"
                    )
                except json.JSONDecodeError:
                    if self.config.get("log_level") == "debug":
                        logger.debug(f"[Anima] 世界观更新返回非 JSON: {text[:100]}")
        except asyncio.TimeoutError:
            logger.warning(
                f"[Anima] 世界观更新超时（>{self.config.get('worldview_update_timeout', 60.0)}s），"
                f"保留旧数据"
            )
        except Exception as e:
            if self.config.get("log_level") == "debug":
                logger.debug(f"[Anima] 世界观更新失败: {e}")

    def _get_worldview_text(self, event: Optional[AstrMessageEvent] = None) -> str:
        """获取世界观注入文本，包含当前对话者的画像"""
        if not self.config.get("worldview_enabled", False):
            return ""
        wv = self._read_worldview()
        if not wv:
            return ""
        parts = []
        env = wv.get("environment", "")
        pos = wv.get("my_position", "")
        norms = wv.get("norms", "")
        if env:
            parts.append(f"对这个世界的理解：{env}")
        if pos:
            parts.append(f"我在这里是：{pos}")
        if norms:
            parts.append(f"这里的规矩：{norms}")
        # 按需注入当前对话者的 social_graph 条目
        social_graph = wv.get("social_graph", {})
        if social_graph and event:
            sender_id = ""
            if hasattr(event, "message_obj") and event.message_obj:
                sender_id = str(getattr(event.message_obj.sender, "user_id", ""))
            if sender_id and sender_id in social_graph:
                parts.append(f"关于 {sender_id}：{social_graph[sender_id]}")
        if not parts:
            return ""
        return "。".join(parts)
