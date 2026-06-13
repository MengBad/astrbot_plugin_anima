"""Snapshot 和 Diff 数据类。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Change:
    """状态变更。"""

    key: str
    old: Any = None
    new: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "old": _safe_serialize(self.old),
            "new": _safe_serialize(self.new),
        }


@dataclass
class Diff:
    """两个快照之间的差异。"""

    changes: list[Change] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "timestamp": self.timestamp,
            "change_count": len(self.changes),
        }


@dataclass
class Snapshot:
    """状态快照。"""

    name: str = "default"
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "data_keys": list(self.data.keys()),
            "data_size": sum(_safe_size(v) for v in self.data.values()),
            "metadata": self.metadata,
        }


def _safe_serialize(value: Any) -> Any:
    """安全序列化值。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k)[:100]: _safe_serialize(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_safe_serialize(item) for item in list(value)[:50]]
    return str(value)[:200]


def _safe_size(value: Any) -> int:
    """安全获取值大小。"""
    try:
        if isinstance(value, (str, bytes)):
            return len(value)
        if isinstance(value, (dict, list, tuple)):
            return len(value)
        return 1
    except Exception:
        return 1
