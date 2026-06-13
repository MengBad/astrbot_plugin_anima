"""StateStore 迁移助手 — 将旧持久化路径接入统一 StateStore。"""

from __future__ import annotations

import os
from typing import Any

from .store import StateStore
from .json_source import JsonStateSource
from .markdown_source import MarkdownStateSource
from .jsonl_source import JsonlStateSource


def register_legacy_sources(store: StateStore, data_dir: str) -> None:
    """将所有旧持久化文件注册到 StateStore。

    Args:
        store: StateStore 实例
        data_dir: 插件数据目录
    """
    # JSON 文件
    json_files = {
        "anima_state": ("anima_state.json", "global", "state"),
        "desires": ("desires.json", "global", "desire"),
        "worldview": ("worldview.json", "legacy/global", "worldview"),
        "time_sense": ("time_sense.json", "legacy/global", "time"),
        "social_graph": ("social_graph.json", "global", "relationship"),
        "contradictions": ("contradictions.json", "global", "reflection"),
        "tool_learning": ("tool_learning.json", "global", "capability"),
        "suppressed_topics": ("suppressed_topics.json", "global", "scar"),
        "scar_dimensions": ("scar_dimensions.json", "global", "scar"),
        "personal_capabilities": ("personal_capabilities.json", "global", "capability"),
    }

    for name, (filename, scope, role) in json_files.items():
        path = os.path.join(data_dir, filename)
        source = JsonStateSource(path, name, scope=scope, role=role)
        store.register_source(name, source)

    # Markdown 文件
    markdown_files = {
        "self_notes": ("self_notes.md", "global", "narrative"),
        "capabilities_diary": ("capabilities_diary.md", "global", "capability"),
        "tool_diary": ("tool_diary.md", "global", "capability"),
    }

    for name, (filename, scope, role) in markdown_files.items():
        path = os.path.join(data_dir, filename)
        source = MarkdownStateSource(path, name, scope=scope, role=role)
        store.register_source(name, source)

    # JSONL 文件
    jsonl_files = {
        "evolution_log": ("evolution_log.jsonl", "global", "timeline"),
        "runtime_events": ("runtime_events.jsonl", "global", "observability"),
    }

    for name, (filename, scope, role) in jsonl_files.items():
        path = os.path.join(data_dir, filename)
        source = JsonlStateSource(path, name, scope=scope, role=role)
        store.register_source(name, source)


def get_store_summary(store: StateStore) -> dict[str, Any]:
    """获取 StateStore 的摘要信息。"""
    sources = store.source_names
    return {
        "total_sources": len(sources),
        "sources": sources,
        "snapshots": store.list_snapshots(),
    }
