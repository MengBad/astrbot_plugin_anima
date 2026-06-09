"""Shared background task container helpers.

The plugin historically used both ``list``-style and ``set``-style APIs for
``_background_tasks``.  A single compatible container keeps old call sites
working while preserving set semantics for shutdown and observability.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class BackgroundTaskSet(set):
    """Set-backed task registry with list-compatible mutators."""

    def append(self, item: Any) -> None:
        self.add(item)

    def extend(self, items: Iterable[Any]) -> None:
        self.update(items)

    def remove(self, item: Any) -> None:  # type: ignore[override]
        self.discard(item)


def ensure_background_tasks(plugin: Any) -> BackgroundTaskSet:
    """Return a compatible ``_background_tasks`` registry for ``plugin``.

    Existing list/set registries are migrated without dropping task handles.
    Custom containers that already expose both list and set APIs are preserved.
    """

    tasks = getattr(plugin, "_background_tasks", None)
    required = ("add", "append", "extend", "discard", "remove", "clear")
    if tasks is not None and all(hasattr(tasks, name) for name in required):
        return tasks  # type: ignore[return-value]

    registry = BackgroundTaskSet()
    if tasks is not None:
        try:
            registry.update(list(tasks))
        except TypeError:
            registry.add(tasks)
    plugin._background_tasks = registry
    return registry
