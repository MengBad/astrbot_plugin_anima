"""Redacted State Inspector snapshots for the Cognitive Observatory."""

from __future__ import annotations

import os
import time
from typing import Any

from sylanne_alpha.state_store_audit import build_state_store_audit_snapshot
from sylanne_alpha.state_persistence import dirty_snapshot


STATE_INSPECTOR_SCHEMA = "anima.state_inspector.v1"


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _file_info(path: str | None) -> dict[str, Any]:
    if not path:
        return {"configured": False, "exists": False}
    try:
        exists = os.path.exists(path)
        info: dict[str, Any] = {
            "configured": True,
            "path": os.path.basename(path),
            "exists": exists,
        }
        if exists:
            stat = os.stat(path)
            info.update({
                "size_bytes": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            })
        return info
    except Exception as exc:
        return {
            "configured": True,
            "path": os.path.basename(str(path)),
            "exists": False,
            "error": type(exc).__name__,
        }


def _host_summary(host: Any) -> dict[str, Any]:
    kernel = getattr(host, "kernel", None)
    comp = getattr(kernel, "computation", None)
    runtime = getattr(host, "runtime", None)
    return {
        "has_kernel": kernel is not None,
        "has_runtime": runtime is not None,
        "turns": int(getattr(kernel, "turns", 0) or 0) if kernel is not None else 0,
        "spine_ticks": int(getattr(comp, "_tick_count", 0) or 0) if comp is not None else 0,
        "last_route": str(getattr(comp, "_last_route", "") or "") if comp is not None else "",
    }


def _session_keys(plugin: Any, dirty: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for attr in (
        "_hosts",
        "_memory_systems",
        "_conversation_buffers",
        "_prompt_debug_snapshots",
        "_last_request_budgets",
        "_background_post_queues",
        "_background_post_worker_state",
    ):
        mapping = getattr(plugin, attr, None)
        if hasattr(mapping, "keys"):
            keys.update(str(key) for key in mapping.keys())
    sessions = dirty.get("sessions") if isinstance(dirty, dict) else {}
    if isinstance(sessions, dict):
        keys.update(str(key) for key in sessions.keys())
    return sorted(keys)


def build_state_inspector_snapshot(plugin: Any) -> dict[str, Any]:
    """Build a redacted state/session consistency snapshot.

    The snapshot intentionally avoids full kernel snapshots, prompt text,
    memory bodies, self notes, and desire content. It is meant to explain
    state topology and persistence readiness without becoming another state
    source.
    """
    dirty = dirty_snapshot()
    hosts = getattr(plugin, "_hosts", {}) or {}
    memory_systems = getattr(plugin, "_memory_systems", {}) or {}
    buffers = getattr(plugin, "_conversation_buffers", {}) or {}
    prompt_debug = getattr(plugin, "_prompt_debug_snapshots", {}) or {}
    request_budgets = getattr(plugin, "_last_request_budgets", {}) or {}
    background_tasks = getattr(plugin, "_background_tasks", None)
    global_dirty = list(dirty.get("global") or []) if isinstance(dirty, dict) else []
    dirty_sessions = dirty.get("sessions") if isinstance(dirty, dict) else {}
    if not isinstance(dirty_sessions, dict):
        dirty_sessions = {}

    sessions: list[dict[str, Any]] = []
    for session_key in _session_keys(plugin, dirty):
        host = hosts.get(session_key) if hasattr(hosts, "get") else None
        session_dirty = sorted(set(global_dirty) | set(dirty_sessions.get(session_key, [])))
        sessions.append({
            "session_key": session_key,
            "has_host": host is not None,
            "has_memory_system": bool(hasattr(memory_systems, "get") and memory_systems.get(session_key) is not None),
            "has_conversation_buffer": bool(hasattr(buffers, "get") and buffers.get(session_key) is not None),
            "has_prompt_debug_snapshot": bool(hasattr(prompt_debug, "get") and prompt_debug.get(session_key) is not None),
            "has_request_budget": bool(hasattr(request_budgets, "get") and request_budgets.get(session_key) is not None),
            "is_dirty": bool(session_dirty),
            "dirty_subsystems": session_dirty,
            "host": _host_summary(host) if host is not None else {},
        })

    isolation_violations: list[str] = []
    try:
        from sylanne_alpha.session_context import validate_session_isolation

        isolation_violations = validate_session_isolation(hosts)
    except Exception:
        isolation_violations = []
    state_store_audit = build_state_store_audit_snapshot(plugin)

    snapshot = {
        "schema": STATE_INSPECTOR_SCHEMA,
        "timestamp": time.time(),
        "summary": {
            "active_hosts": _safe_len(hosts),
            "memory_systems": _safe_len(memory_systems),
            "conversation_buffers": _safe_len(buffers),
            "prompt_debug_snapshots": _safe_len(prompt_debug),
            "last_request_budgets": _safe_len(request_budgets),
            "background_tasks": _safe_len(background_tasks),
            "dirty_sessions": len(dirty_sessions),
            "global_dirty_subsystems": global_dirty,
            "kv_api_available": bool(
                hasattr(plugin, "put_kv_data") and callable(plugin.put_kv_data)
            ),
            "sylanne_ready": bool(
                getattr(plugin, "_sylanne_ready", lambda: False)()
            ),
            "isolation_violation_count": len(isolation_violations),
            "state_sources": int(
                state_store_audit.get("summary", {}).get("configured_files", 0) or 0
            ),
            "state_store_complete": bool(
                state_store_audit.get("summary", {}).get("state_store_complete", False)
            ),
        },
        "sessions": sessions,
        "persistence_files": {
            "anima_state": _file_info(getattr(plugin, "_state_path", None)),
            "self_notes": _file_info(getattr(plugin, "self_notes_path", None)),
            "desires": _file_info(getattr(plugin, "desires_path", None)),
            "runtime_events": _file_info(
                os.path.join(str(getattr(plugin, "data_dir", "") or ""), "runtime_events.jsonl")
            ),
        },
        "state_store_audit": state_store_audit,
        "dirty": dirty,
        "isolation_violations": isolation_violations[:20],
    }
    return snapshot
