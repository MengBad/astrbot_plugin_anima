"""Markdown 文件状态源实现。"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

from .base import StateSource


class MarkdownStateSource:
    """Markdown 文件状态源。"""

    def __init__(
        self,
        path: str,
        name: str,
        scope: str = "global",
        role: str = "narrative",
    ):
        self._path = path
        self._name = name
        self._scope = scope
        self._role = role

    @property
    def name(self) -> str:
        return self._name

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def format(self) -> str:
        return "markdown"

    @property
    def role(self) -> str:
        return self._role

    async def read(self) -> str:
        """读取 Markdown 文件。"""
        if not os.path.exists(self._path):
            return ""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    async def write(self, data: str) -> None:
        """原子写入 Markdown 文件。"""
        dir_name = os.path.dirname(self._path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            shutil.move(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

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
        return {
            "name": self._name,
            "exists": True,
            "path": os.path.basename(self._path),
            "size_bytes": int(stat.st_size),
            "mtime": float(stat.st_mtime),
            "scope": self._scope,
            "format": self.format,
            "role": self._role,
        }
