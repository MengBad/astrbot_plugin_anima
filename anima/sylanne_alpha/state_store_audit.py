"""Read-only StateStore precursor audit snapshots.

This module does not introduce a new persistence layer yet.  It inventories the
current multi-source state topology so operators can see what would eventually
move behind a unified StateStore without exposing state contents.
"""

from __future__ import annotations

import os
import hashlib
import json
import time
from typing import Any


STATE_STORE_AUDIT_SCHEMA = "anima.state_store_audit.v1"


_FILE_SOURCES = (
    ("anima_state", "_state_path", "global", "json", "state"),
    ("self_notes", "self_notes_path", "global", "markdown", "narrative"),
    ("evolution_log", "evolution_log_path", "global", "jsonl", "timeline"),
    ("persona_core", "persona_core_path", "global", "yaml", "personality"),
    ("desires", "desires_path", "global", "json", "desire"),
    ("worldview", "worldview_path", "legacy/global", "json", "worldview"),
    ("time_sense", "time_sense_path", "legacy/global", "json", "time"),
    ("social_graph", "social_graph_path", "global", "json", "relationship"),
    ("contradictions", "contradictions_path", "global", "json", "reflection"),
    ("tool_learning", "tool_learning_path", "global", "json", "capability"),
    ("tool_diary", "tool_diary_path", "global", "markdown", "capability"),
    ("suppressed_topics", "suppressed_topics_path", "global", "json", "scar"),
    ("scar_dimensions", "scar_dimensions_path", "global", "json", "scar"),
    ("personal_capabilities", "personal_capabilities_path", "global", "json", "capability"),
    ("capabilities_diary", "capabilities_diary_path", "global", "markdown", "capability"),
)

_RUNTIME_SOURCES = (
    ("hosts", "_hosts", "session", "sylanne"),
    ("memory_systems", "_memory_systems", "session", "memory"),
    ("conversation_buffers", "_conversation_buffers", "session", "memory"),
    ("prompt_debug_snapshots", "_prompt_debug_snapshots", "session", "observability"),
    ("last_request_budgets", "_last_request_budgets", "session", "prompt"),
    ("background_tasks", "_background_tasks", "runtime", "lifecycle"),
    ("background_post_queues", "_background_post_queues", "session", "lifecycle"),
)


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _basename(path: str | None) -> str:
    return os.path.basename(str(path or ""))


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _file_source(plugin: Any, name: str, attr: str, scope: str, fmt: str, role: str) -> dict[str, Any]:
    path = getattr(plugin, attr, None)
    item: dict[str, Any] = {
        "name": name,
        "kind": "file",
        "scope": scope,
        "format": fmt,
        "role": role,
        "configured": bool(path),
        "exists": False,
        "path": _basename(path),
        "content": "redacted",
    }
    if not path:
        return item
    try:
        exists = os.path.exists(path)
        item["exists"] = bool(exists)
        if exists:
            stat = os.stat(path)
            item["size_bytes"] = int(stat.st_size)
            item["mtime"] = float(stat.st_mtime)
            item["mtime_ns"] = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
    except Exception as exc:
        item["error"] = type(exc).__name__
    item["metadata_fingerprint"] = _fingerprint({
        "name": item.get("name", ""),
        "kind": item.get("kind", ""),
        "scope": item.get("scope", ""),
        "format": item.get("format", ""),
        "role": item.get("role", ""),
        "configured": bool(item.get("configured")),
        "exists": bool(item.get("exists")),
        "size_bytes": int(item.get("size_bytes", 0) or 0),
        "mtime_ns": int(item.get("mtime_ns", 0) or 0),
        "error": str(item.get("error", "") or ""),
    })
    return item


def _runtime_source(plugin: Any, name: str, attr: str, scope: str, role: str) -> dict[str, Any]:
    value = getattr(plugin, attr, None)
    return {
        "name": name,
        "kind": "runtime",
        "scope": scope,
        "role": role,
        "configured": value is not None,
        "entries": _safe_len(value),
        "content": "redacted",
    }


def _session_file_summary(plugin: Any) -> dict[str, Any]:
    data_dir = str(getattr(plugin, "data_dir", "") or "")
    sessions_dir = os.path.join(data_dir, "sessions") if data_dir else ""
    summary: dict[str, Any] = {
        "configured": bool(data_dir),
        "exists": False,
        "session_dirs": 0,
        "worldview_files": 0,
        "time_sense_files": 0,
    }
    try:
        if sessions_dir and os.path.isdir(sessions_dir):
            summary["exists"] = True
            for entry in os.scandir(sessions_dir):
                if not entry.is_dir():
                    continue
                summary["session_dirs"] += 1
                if os.path.exists(os.path.join(entry.path, "worldview.json")):
                    summary["worldview_files"] += 1
                if os.path.exists(os.path.join(entry.path, "time_sense.json")):
                    summary["time_sense_files"] += 1
    except Exception as exc:
        summary["error"] = type(exc).__name__
    return summary


def build_state_store_audit_snapshot(plugin: Any) -> dict[str, Any]:
    """Inventory current state sources without reading their contents."""
    files = [_file_source(plugin, *spec) for spec in _FILE_SOURCES]
    runtime = [_runtime_source(plugin, *spec) for spec in _RUNTIME_SOURCES]
    runtime_events = _file_source(
        plugin,
        "runtime_events",
        "_runtime_events_path",
        "global",
        "jsonl",
        "observability",
    )
    if not runtime_events.get("configured"):
        data_dir = str(getattr(plugin, "data_dir", "") or "")
        runtime_events = _file_source(
            type("_RuntimeEventsPath", (), {
                "_runtime_events_path": os.path.join(data_dir, "runtime_events.jsonl") if data_dir else ""
            })(),
            "runtime_events",
            "_runtime_events_path",
            "global",
            "jsonl",
            "observability",
        )
    files.append(runtime_events)

    configured_files = [item for item in files if item.get("configured")]
    existing_files = [item for item in configured_files if item.get("exists")]
    missing_files = [item["name"] for item in configured_files if not item.get("exists")]
    sessions = _session_file_summary(plugin)
    kv_available = bool(hasattr(plugin, "put_kv_data") and callable(plugin.put_kv_data))
    warnings: list[str] = []
    if missing_files:
        warnings.append("configured_files_missing")
    if sessions.get("session_dirs", 0) and not sessions.get("exists"):
        warnings.append("session_dir_unreadable")
    if not kv_available:
        warnings.append("kv_api_unavailable")
    source_fingerprint = _fingerprint({
        "files": [
            {
                "name": item.get("name", ""),
                "metadata_fingerprint": item.get("metadata_fingerprint", ""),
            }
            for item in configured_files
        ],
        "runtime": [
            {
                "name": item.get("name", ""),
                "entries": int(item.get("entries", 0) or 0),
            }
            for item in runtime
        ],
        "sessions": sessions,
        "kv_api_available": kv_available,
    })

    return {
        "schema": STATE_STORE_AUDIT_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "files": "only basename, existence, size, and mtime are exposed",
            "runtime": "only container names and entry counts are exposed",
            "sessions": "only aggregate session file counts are exposed",
        },
        "summary": {
            "state_store_complete": False,
            "configured_files": len(configured_files),
            "existing_files": len(existing_files),
            "missing_files": len(missing_files),
            "runtime_sources": len(runtime),
            "runtime_entries": sum(int(item.get("entries", 0) or 0) for item in runtime),
            "session_dirs": int(sessions.get("session_dirs", 0) or 0),
            "kv_api_available": kv_available,
            "timeline_available": bool(runtime_events.get("exists")),
            "diff_ready_sources": len(existing_files),
            "source_fingerprint": source_fingerprint,
            "warnings": warnings,
        },
        "capabilities": {
            "snapshot": "partial",
            "diff": "metadata_ready",
            "rollback": "partial_persona_core_only",
            "audit": "read_only_inventory",
            "timeline": "runtime_events_jsonl",
        },
        "files": files,
        "runtime": runtime,
        "session_files": sessions,
    }
