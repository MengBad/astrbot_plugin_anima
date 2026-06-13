"""StateStore 统一状态存储主类。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import StateSource
from .snapshot import Snapshot, Diff, Change


class StateStore:
    """统一的状态存储抽象层。"""

    def __init__(self, data_dir: str | None = None):
        self._data_dir = data_dir
        self._sources: dict[str, StateSource] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._max_snapshots: int = 10

    def register_source(self, name: str, source: StateSource) -> None:
        """注册状态源。"""
        self._sources[name] = source

    def unregister_source(self, name: str) -> None:
        """注销状态源。"""
        self._sources.pop(name, None)

    def get_source(self, name: str) -> StateSource | None:
        """获取状态源。"""
        return self._sources.get(name)

    @property
    def source_names(self) -> list[str]:
        """获取所有状态源名称。"""
        return list(self._sources.keys())

    async def snapshot(
        self,
        name: str = "default",
        scope: str = "all",
    ) -> Snapshot:
        """创建一致性快照。"""
        snapshot = Snapshot(
            name=name,
            timestamp=time.time(),
            metadata={"scope": scope, "source_count": len(self._sources)},
        )

        for source_name, source in self._sources.items():
            if scope != "all" and source.scope != scope:
                continue
            try:
                data = await source.read()
                snapshot.data[source_name] = data
            except Exception as exc:
                snapshot.data[source_name] = None
                snapshot.metadata[f"error_{source_name}"] = str(exc)

        self._snapshots[name] = snapshot
        self._trim_snapshots()
        return snapshot

    async def diff(self, old: Snapshot, new: Snapshot) -> Diff:
        """计算两个快照之间的差异。"""
        diff = Diff()

        all_keys = set(old.data.keys()) | set(new.data.keys())
        for key in sorted(all_keys):
            old_val = old.data.get(key)
            new_val = new.data.get(key)
            if old_val != new_val:
                diff.changes.append(Change(key=key, old=old_val, new=new_val))

        return diff

    async def rollback(self, snapshot: Snapshot) -> None:
        """回滚到指定快照。"""
        for source_name, data in snapshot.data.items():
            if source_name in self._sources:
                try:
                    await self._sources[source_name].write(data)
                except Exception as exc:
                    pass

    async def metadata(self) -> dict[str, Any]:
        """获取所有状态源的元数据。"""
        sources_meta = {}
        for name, source in self._sources.items():
            try:
                sources_meta[name] = await source.metadata()
            except Exception as exc:
                sources_meta[name] = {"error": str(exc)}

        return {
            "source_count": len(self._sources),
            "snapshot_count": len(self._snapshots),
            "sources": sources_meta,
            "snapshot_names": list(self._snapshots.keys()),
        }

    def get_snapshot(self, name: str) -> Snapshot | None:
        """获取指定名称的快照。"""
        return self._snapshots.get(name)

    def list_snapshots(self) -> list[str]:
        """列出所有快照名称。"""
        return list(self._snapshots.keys())

    def delete_snapshot(self, name: str) -> bool:
        """删除指定快照。"""
        if name in self._snapshots:
            del self._snapshots[name]
            return True
        return False

    def _trim_snapshots(self) -> None:
        """修剪快照数量。"""
        while len(self._snapshots) > self._max_snapshots:
            oldest = min(self._snapshots.keys(), key=lambda k: self._snapshots[k].timestamp)
            del self._snapshots[oldest]
