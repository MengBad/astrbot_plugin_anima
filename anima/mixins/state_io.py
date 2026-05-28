"""
StateIOMixin —— 通用工具方法 + state IO
=================================
v0.8.0 从 main.py 抽出：# ==================== 通用工具方法 ====================

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


class StateIOMixin:
    """通用工具方法 + state IO mixin（从 main.py 自动抽出）。所有方法依赖宿主类提供的 self.* 状态。"""

    def _is_rejected(self, text: str) -> bool:
        """检查文本是否包含拒绝短语（v0.7.0 委托给 anima.filters）"""
        reject_phrases = self.config.get("reject_phrases", None)
        return _ext_is_rejected(text, reject_phrases)

    def _is_sensitive(self, text: str) -> bool:
        """检查文本是否包含敏感内容（v0.7.0 委托给 anima.filters）"""
        return _ext_is_sensitive(text)

    async def _get_provider_id(self, event: Optional[AstrMessageEvent] = None, prefer: str = "") -> str:
        """获取要使用的 Provider ID。
        优先级：prefer 参数 > internal_provider_id 配置 > 当前对话主模型 > 第一个可用 chat provider
        允许 event=None（用于离线反刍、定时任务、工具反思等没有当前 event 的场景）。
        失败时返回空串而不抛异常，调用方按 falsy 兜底。
        """
        if prefer:
            return prefer
        internal = self.config.get("internal_provider_id", "")
        if internal:
            return internal
        # 有 event 时尝试取当前 umo 绑定的对话模型
        if event is not None and getattr(event, "unified_msg_origin", None):
            try:
                pid = await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
                if pid:
                    return pid
            except Exception as e:
                logger.debug(f"[Anima] get_current_chat_provider_id 失败: {e}")
        # 兜底：返回第一个可用的 chat provider id
        try:
            providers = self.context.get_all_providers()
            if providers:
                return providers[0].meta().id
        except Exception as e:
            logger.debug(f"[Anima] 兜底获取 chat provider 失败: {e}")
        return ""

    def _read_json(self, path: str, default=None):
        """安全读取 JSON 文件"""
        if default is None:
            default = {}
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, path: str, data):
        """安全写入 JSON 文件（持锁，避免并发交错）"""
        try:
            with self._io_lock:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"[Anima] 写入 {path} 失败: {e}")
        except Exception as e:
            logger.warning(f"[Anima] 写入 {path} 异常: {e}")

    def _load_state(self) -> dict:
        """加载持久化状态"""
        return self._read_json(self._state_path, default={})

    def _atomic_update_state(self, updater):
        """原子地"读-改-写"持久化状态。
        updater 是一个 (state: dict) -> None 的回调，对传入的 dict 做就地修改。
        整个读改写过程持 _io_lock，避免并发更新丢失。
        """
        with self._io_lock:
            try:
                if os.path.exists(self._state_path):
                    with open(self._state_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                else:
                    state = {}
            except (json.JSONDecodeError, OSError):
                state = {}
            try:
                updater(state)
            except Exception as e:
                logger.warning(f"[Anima] state updater 回调失败: {e}")
                return
            try:
                with open(self._state_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
            except OSError as e:
                logger.warning(f"[Anima] 写入 state 失败: {e}")

    def _save_state(self):
        """保存持久化状态（原子读-改-写）"""
        def _update(state: dict):
            state["sediment_count"] = self._sediment_count
            state["identity_stability"] = self._identity_stability
            state["last_active_umo"] = self._last_active_umo
            # Phase 3: 同步人格向量（如果已缓存）
            if hasattr(self, "_personality_vector") and self._personality_vector:
                state["personality_vector"] = self._personality_vector
        self._atomic_update_state(_update)
