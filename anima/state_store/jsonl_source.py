"""JSONL 文件状态源实现。"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from .base import StateSource


class JsonlStateSource:
    """JSONL 文件状态源（append-only）。"""

    def __init__(
        self,
        path: str,
        name: str,
        scope: str = "global",
        role: str = "timeline",
        max_lines: int = 10000,
    ):
        self._path = path
        self._name = name
        self._scope = scope
        self._role = role
        self._max_lines = max_lines
        self._write_lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def format(self) -> str:
        return "jsonl"

    @property
    def role(self) -> str:
        return self._role

    async def read(self) -> list[dict[str, Any]]:
        """读取所有 JSONL 行。"""
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            events = []
            for line in lines[-self._max_lines:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except json.JSONDecodeError:
                    continue
            return events
        except OSError:
            return []

    async def write(self, data: list[dict[str, Any]]) -> None:
        """覆写整个 JSONL 文件。"""
        dir_name = os.path.dirname(self._path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with self._write_lock:
            with open(self._path, "w", encoding="utf-8") as f:
                for event in data[-self._max_lines:]:
                    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                    f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    async def append(self, event: dict[str, Any]) -> None:
        """追加一条事件。"""
        dir_name = os.path.dirname(self._path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with self._write_lock:
            with open(self._path, "a", encoding="utf-8") as f:
                line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    async def exists(self) -> bool:
        return os.path.exists(self._path)

    async def metadata(self) -> dict[str, Any]:
        """获取文件元数据。"""
        if not os.path.exists(self._path):
            return {
                "name": self._name,
                "exists": False,
                "path": os.path.basename(self._path),
            }
        stat = os.stat(self._path)
        line_count = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
        except OSError:
            pass
        return {
            "name": self._name,
            "exists": True,
            "path": os.path.basename(self._path),
            "size_bytes": int(stat.st_size),
            "mtime": float(stat.st_mtime),
            "scope": self._scope,
            "format": self.format,
            "role": self._role,
            "line_count": line_count,
        }
