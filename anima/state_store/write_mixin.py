"""StateStore 写入混合类 — 为现有 mixin 提供 StateStore 写入能力。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any

from .store import StateStore
from .json_source import JsonStateSource
from .markdown_source import MarkdownStateSource
from .jsonl_source import JsonlStateSource


class StateStoreWriteMixin:
    """提供 StateStore 写入能力的 mixin。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state_store: StateStore | None = None

    def _init_state_store(self, data_dir: str) -> None:
        """初始化 StateStore。"""
        from .migration import register_legacy_sources
        self._state_store = StateStore(data_dir=data_dir)
        register_legacy_sources(self._state_store, data_dir)

    async def _write_state(self, name: str, data: Any) -> bool:
        """通过 StateStore 写入状态。"""
        if self._state_store is None:
            return False
        source = self._state_store.get_source(name)
        if source is None:
            return False
        try:
            await source.write(data)
            return True
        except Exception as exc:
            return False

    async def _read_state(self, name: str) -> Any:
        """通过 StateStore 读取状态。"""
        if self._state_store is None:
            return None
        source = self._state_store.get_source(name)
        if source is None:
            return None
        try:
            return await source.read()
        except Exception:
            return None

    async def _write_self_notes(self, content: str) -> bool:
        """通过 StateStore 写入 self_notes。"""
        return await self._write_state("self_notes", content)

    async def _read_self_notes(self) -> str:
        """通过 StateStore 读取 self_notes。"""
        result = await self._read_state("self_notes")
        return result if isinstance(result, str) else ""

    async def _write_desires(self, data: dict) -> bool:
        """通过 StateStore 写入 desires。"""
        return await self._write_state("desires", data)

    async def _read_desires(self) -> dict:
        """通过 StateStore 读取 desires。"""
        result = await self._read_state("desires")
        return result if isinstance(result, dict) else {}

    async def _write_state_data(self, data: dict) -> bool:
        """通过 StateStore 写入 anima_state。"""
        return await self._write_state("anima_state", data)

    async def _read_state_data(self) -> dict:
        """通过 StateStore 读取 anima_state。"""
        result = await self._read_state("anima_state")
        return result if isinstance(result, dict) else {}
