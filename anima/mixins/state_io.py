"""
StateIOMixin —— 通用工具方法 + state IO
=================================
v0.8.0 从 main.py 抽出：# ==================== 通用工具方法 ====================

依赖宿主类（AnimaPlugin）提供 self.* 状态字段（self.config / self.context / self.data_dir / self._io_lock 等）。
"""
from __future__ import annotations

import asyncio
import hashlib
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

from ..filters import (
    is_rejected as _ext_is_rejected,
    is_sensitive as _ext_is_sensitive,
    is_injection as _ext_is_injection,
    is_error_artifact as _ext_is_error_artifact,
    strip_markdown_artifacts as _ext_strip_markdown,
)
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

    @staticmethod
    def _compose_system_prompt(persona_prompt: str, existing_sys: str) -> str:
        """v0.9.7: 把人设 prompt 前置合并到既有 system prompt。
        - persona_prompt 在前，原 system 在后，换行分隔
        - 幂等：persona_prompt 已包含在 existing_sys 中则不重复叠加
          （防框架重试 / 多次进 hook 导致 system prompt 越拼越长）
        """
        persona_prompt = (persona_prompt or "").strip()
        existing_sys = existing_sys or ""
        if not persona_prompt:
            return existing_sys
        if persona_prompt in existing_sys:
            return existing_sys
        return persona_prompt + ("\n\n" + existing_sys if existing_sys else "")

    def _validate_persona_prompt_once(self, persona_prompt: str):
        """v0.9.8: 人设 prompt 轻量校验（一次性日志，按内容去重防刷屏）。
        - 注入/越狱文本检测：命中则告警（不阻断注入，只提示用户可能写了风险内容）
        - 超长警告：超过 persona_prompt_warn_chars（默认 2000）提示会显著增加每轮输入 token
        校验只产生日志，绝不抛异常、绝不阻断注入。"""
        try:
            # 按内容指纹去重，同一份人设只告警一次（用户改了才会再次校验）
            fp = hash(persona_prompt)
            if getattr(self, "_persona_prompt_validated_fp", None) == fp:
                return
            self._persona_prompt_validated_fp = fp

            # 注入/越狱检测
            try:
                if self._is_injection(persona_prompt):
                    logger.warning(
                        "[Anima] persona_prompt 命中注入/越狱特征词，请确认这是有意的人设内容"
                        "（仍会按配置注入，但可能影响模型行为）"
                    )
            except Exception:
                pass

            # 超长警告
            warn_chars = int(self.config.get("persona_prompt_warn_chars", 2000))
            n = len(persona_prompt)
            if n > warn_chars:
                logger.warning(
                    f"[Anima] persona_prompt 较长（{n} 字符 > {warn_chars}），"
                    f"会显著增加每轮 system prompt 的输入 token，建议精简"
                )
        except Exception:
            pass

    def _is_rejected(self, text: str) -> bool:
        """检查文本是否包含拒绝短语（v0.7.0 委托给 anima.filters）"""
        reject_phrases = self.config.get("reject_phrases", None)
        return _ext_is_rejected(text, reject_phrases)

    def _is_sensitive(self, text: str) -> bool:
        """检查文本是否包含敏感内容（v0.7.0 委托给 anima.filters）"""
        return _ext_is_sensitive(text)

    def _is_injection(self, text: str) -> bool:
        """检查文本是否为 prompt 注入 / 越狱文本（v0.8.5 委托给 anima.filters）。

        支持通过配置项 injection_phrases 自定义短语列表。
        """
        injection_phrases = self.config.get("injection_phrases", None)
        return _ext_is_injection(text, injection_phrases)

    def _is_error_artifact(self, text: str) -> bool:
        """检查文本是否为框架 / 运行时错误文本（v0.8.7 委托给 anima.filters）。

        拦截 "Error occurred during AI execution..." / traceback /
        "database is locked" 等被框架当成 bot 回复记录下来的错误文本，
        避免它们进入向量记忆并被检索注入污染上下文。
        支持通过配置项 error_artifact_phrases 自定义短语列表。
        """
        error_phrases = self.config.get("error_artifact_phrases", None)
        return _ext_is_error_artifact(text, error_phrases)

    def _strip_markdown(self, text: str) -> str:
        """剥离 Markdown 代码标记（反引号 / 代码块），用于纯文本记忆（v0.8.7）。

        防止模型用反引号包颜文字（QQ 不渲染会原样显示），且阻断带反引号的
        回复被存入记忆后检索注入、让模型继续模仿的格式自我强化循环。
        """
        return _ext_strip_markdown(text)

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

    # ── v0.9.8: 会话级隔离基础设施（per-umo 子目录 + 全局回退） ──────────────

    def _safe_umo(self, umo: str) -> str:
        """把 umo 转成安全目录名（v0.9.8）。
        - 空 umo → '_default_'
        - 非 [A-Za-z0-9_-] 字符替换为 '_'（天然防路径穿越：.. / / \\ 都被替换）
        - 附加原始 umo 的 md5 前 8 位哈希后缀，保证不同 umo 不碰撞
        """
        if not umo:
            return "_default_"
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', umo).strip('_')
        if not safe:
            safe = "umo"
        h = hashlib.md5(umo.encode("utf-8")).hexdigest()[:8]
        return f"{safe[:40]}_{h}"

    def _session_dir(self, umo: str) -> str:
        """返回某 umo 的会话目录 data_dir/sessions/<safe_umo>/，确保存在。"""
        d = os.path.join(self.data_dir, "sessions", self._safe_umo(umo))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            logger.warning(f"[Anima] 创建会话目录失败: {e}")
        return d

    def _session_path(self, umo: str, filename: str) -> str:
        """返回某 umo 会话目录下指定文件的完整路径。"""
        return os.path.join(self._session_dir(umo), filename)

    def _resolve_umo(self, umo: str = "") -> str:
        """umo 为空时回退到最近活跃 umo（用于无 event 的后台路径）。"""
        return umo or getattr(self, "_last_active_umo", "") or ""

    def _read_session_json(self, umo: str, filename: str, global_path: str, default=None):
        """读会话文件；不存在则回退全局文件（向后兼容老数据）；都没有返回 default。
        default 支持 callable（返回默认结构）或值。"""
        umo = self._resolve_umo(umo)

        def _mk_default():
            if callable(default):
                return default()
            if default is None:
                return {}
            return default

        sp = self._session_path(umo, filename)
        if os.path.exists(sp):
            return self._read_json(sp, default=_mk_default())
        # 全局回退：升级后某 umo 首次读，读旧全局文件作为初始值
        if global_path and os.path.exists(global_path):
            return self._read_json(global_path, default=_mk_default())
        return _mk_default()

    def _write_session_json(self, umo: str, filename: str, data):
        """只写某 umo 的会话文件（复用 _write_json 持锁）。不写全局文件。"""
        umo = self._resolve_umo(umo)
        self._write_json(self._session_path(umo, filename), data)


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
