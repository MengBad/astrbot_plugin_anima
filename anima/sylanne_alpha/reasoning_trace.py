"""Redacted Reasoning Trace snapshots for the Cognitive Observatory."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any


REASONING_TRACE_SCHEMA = "anima.reasoning_trace.v1"

_TRACE_EVENT_TYPES = {
    "prompt.injection_assembled",
    "tool.invocation_started",
    "tool.invocation_finished",
    "response.observed",
    "memory.recall_performed",
    "memory.recall_replay_snapshot",
    "memory.explorer_snapshot",
    "desire.dashboard_snapshot",
    "scar.explorer_snapshot",
    "personality.drift_snapshot",
    "state.inspector_snapshot",
    "state.store_audit_snapshot",
    "persistence.shutdown_flush_started",
    "persistence.shutdown_flush_finished",
    "background_tasks.cancelled",
    "background_tasks.snapshot",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _safe_request_shape(value: Any) -> dict[str, int | bool]:
    """Keep only non-sensitive shape counters from prompt debug snapshots."""
    if not isinstance(value, dict):
        return {}
    safe: dict[str, int | bool] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            safe[str(key)[:80]] = item
        elif isinstance(item, int):
            safe[str(key)[:80]] = item
    return safe


def _safe_metadata_list(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    safe: list[Any] = []
    for item in value[:20]:
        if isinstance(item, bool):
            safe.append(item)
        elif isinstance(item, int):
            safe.append(item)
        elif isinstance(item, float):
            safe.append(_safe_float(item))
        elif isinstance(item, str):
            safe.append(item[:120])
    return safe


def _generic_safe_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Fallback evidence must never expose arbitrary state, prompt, or message bodies."""
    safe: dict[str, Any] = {}
    safe_string_keys = {
        "schema",
        "status",
        "source",
        "category",
        "phase",
        "state",
        "warning_level",
    }
    safe_list_keys = {
        "arg_keys",
        "flags",
        "injected_slots",
        "payload_keys",
        "skipped_slots",
        "tags",
        "warnings",
    }
    for raw_key, value in payload.items():
        key = str(raw_key)[:80]
        key_lower = key.lower()
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int):
            safe[key] = value
        elif isinstance(value, float):
            safe[key] = _safe_float(value)
        elif isinstance(value, str):
            if (
                key_lower in safe_string_keys
                or key_lower.endswith("_id")
                or "fingerprint" in key_lower
                or "hash" in key_lower
            ):
                safe[key] = value[:120]
        elif key_lower in safe_list_keys:
            items = _safe_metadata_list(value)
            if items:
                safe[key] = items
    return safe


def _recent_prompt_debug(plugin: Any, *, session_key: str = "") -> list[dict[str, Any]]:
    snapshots = getattr(plugin, "_prompt_debug_snapshots", None)
    if not snapshots:
        return []
    values = list(snapshots.values()) if hasattr(snapshots, "values") else []
    rows: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if session_key and item.get("session_key") != session_key:
            continue
        rows.append({
            "timestamp": _safe_float(item.get("timestamp", 0.0)),
            "session_key": str(item.get("session_key", "") or ""),
            "budget_chars": _safe_int(item.get("budget_chars", 0)),
            "gap_seconds": _safe_float(item.get("gap_seconds", 0.0)),
            "compat_mode": str(item.get("compat_mode", "") or "")[:80],
            "injection_path": str(item.get("injection_path", "") or "")[:80],
            "injected_slots": list(item.get("injected_slots", []) or [])[:12],
            "skipped_slots": list(item.get("skipped_slots", []) or [])[:12],
            "trimmed_total_chars": _safe_int(item.get("trimmed_total_chars", 0)),
            "raw_total_chars": _safe_int(item.get("raw_total_chars", 0)),
            "request_shape": _safe_request_shape(item.get("request_shape", {})),
        })
    return sorted(rows, key=lambda row: row["timestamp"], reverse=True)


def _event_step(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("type", "") or "")
    step: dict[str, Any] = {
        "id": _safe_int(event.get("id", 0)),
        "timestamp": _safe_float(event.get("ts", 0.0)),
        "type": event_type[:120],
        "severity": str(event.get("severity", "") or "info")[:40],
        "source": str(event.get("source", "") or "")[:120],
        "session_key": str(event.get("session_key", "") or "")[:240],
        "tags": list(event.get("tags", []) or [])[:12],
        "payload_keys": sorted(str(key)[:80] for key in payload.keys())[:25],
    }
    if event_type == "prompt.injection_assembled":
        step["decision"] = "assemble_prompt_injection"
        step["evidence"] = {
            "budget_chars": _safe_int(payload.get("budget_chars", 0)),
            "injection_path": str(payload.get("injection_path", "") or "")[:80],
            "injected_slots": list(payload.get("injected_slots", []) or [])[:12],
            "skipped_slots": list(payload.get("skipped_slots", []) or [])[:12],
            "trimmed_total_chars": _safe_int(payload.get("trimmed_total_chars", 0)),
            "raw_total_chars": _safe_int(payload.get("raw_total_chars", 0)),
        }
    elif event_type.startswith("tool.invocation"):
        step["decision"] = "llm_tool_use"
        step["evidence"] = {
            "tool_name": str(payload.get("tool_name", "") or "")[:120],
            "arg_keys": list(payload.get("arg_keys", []) or [])[:20],
            "arg_chars": _safe_int(payload.get("arg_chars", 0)),
            "result_chars": _safe_int(payload.get("result_chars", 0)),
            "success": payload.get("success"),
        }
    elif event_type == "response.observed":
        step["decision"] = "observe_response"
        step["evidence"] = {
            "text_chars": _safe_int(payload.get("text_chars", 0)),
            "confidence": _safe_float(payload.get("confidence", 0.0)),
            "flags": list(payload.get("flags", []) or [])[:12],
        }
    elif event_type == "memory.recall_performed":
        step["decision"] = "memory_recall"
        step["evidence"] = {
            "query_chars": _safe_int(payload.get("query_chars", 0)),
            "query_fingerprint": str(payload.get("query_fingerprint", "") or "")[:40],
            "gap_seconds": _safe_float(payload.get("gap_seconds", 0.0)),
            "recall_limit": _safe_int(payload.get("recall_limit", 0)),
            "result_count": _safe_int(payload.get("result_count", 0)),
            "l2_recalled_count": _safe_int(payload.get("l2_recalled_count", 0)),
        }
    elif event_type == "state.store_audit_snapshot":
        step["decision"] = "state_store_audit_snapshot"
        step["evidence"] = {
            "configured_files": _safe_int(payload.get("configured_files", 0)),
            "existing_files": _safe_int(payload.get("existing_files", 0)),
            "missing_files": _safe_int(payload.get("missing_files", 0)),
            "runtime_sources": _safe_int(payload.get("runtime_sources", 0)),
            "runtime_entries": _safe_int(payload.get("runtime_entries", 0)),
            "diff_ready_sources": _safe_int(payload.get("diff_ready_sources", 0)),
            "source_fingerprint": str(payload.get("source_fingerprint", "") or "")[:40],
            "kv_api_available": bool(payload.get("kv_api_available", False)),
            "timeline_available": bool(payload.get("timeline_available", False)),
        }
    else:
        step["decision"] = event_type.replace(".", "_")[:120]
        step["evidence"] = _generic_safe_evidence(payload)
    return step


def build_reasoning_trace_snapshot(
    plugin: Any, *, session_key: str = "", limit: int = 80
) -> dict[str, Any]:
    """Build a redacted reasoning trace from existing observability sources."""
    limit = max(1, min(300, int(limit or 80)))
    bus = getattr(plugin, "_runtime_event_bus", None)
    events: list[dict[str, Any]] = []
    if bus is not None and hasattr(bus, "recent"):
        events = bus.recent(limit=limit * 2, session_key=session_key)
    trace_events = [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("type", "")) in _TRACE_EVENT_TYPES
    ][:limit]
    steps = sorted((_event_step(event) for event in trace_events), key=lambda step: step["timestamp"])
    by_type = Counter(step["type"] for step in steps)
    prompt_debug = _recent_prompt_debug(plugin, session_key=session_key)[:10]

    request_budgets = getattr(plugin, "_last_request_budgets", {}) or {}
    budget_sessions = []
    if hasattr(request_budgets, "items"):
        for key, value in list(request_budgets.items())[:50]:
            if session_key and str(key) != session_key:
                continue
            data = value if isinstance(value, dict) else {}
            budget_sessions.append({
                "session_key": str(key),
                "budget_chars": _safe_int(data.get("budget_chars", data.get("total_budget", 0))),
                "compat_mode": str(data.get("compat_mode", "") or "")[:80],
                "injected": list(data.get("injected", []) or [])[:12],
                "skipped": list(data.get("skipped", []) or [])[:12],
            })

    return {
        "schema": REASONING_TRACE_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "prompt": "prompt text omitted; slot names, lengths, and request shape only",
            "tools": "tool args/results omitted; names, keys, lengths, and success signals only",
            "responses": "response text omitted; length, flags, and confidence only",
        },
        "summary": {
            "steps": len(steps),
            "source_events": len(events),
            "prompt_debug_snapshots": len(prompt_debug),
            "session_filter": session_key,
            "by_type": dict(by_type),
        },
        "steps": steps,
        "prompt_debug": prompt_debug,
        "request_budgets": budget_sessions,
    }
