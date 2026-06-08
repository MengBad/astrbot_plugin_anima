"""Redacted Session Replay snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from typing import Any


SESSION_REPLAY_SCHEMA = "anima.session_replay.v1"

_REPLAY_EVENT_TYPES = {
    "prompt.injection_assembled",
    "tool.invocation_started",
    "tool.invocation_finished",
    "response.observed",
    "memory.recall_performed",
    "memory.recall_replay_snapshot",
    "reasoning.trace_snapshot",
    "state.inspector_snapshot",
    "memory.explorer_snapshot",
    "desire.dashboard_snapshot",
    "scar.explorer_snapshot",
    "personality.drift_snapshot",
    "persistence.shutdown_flush_started",
    "persistence.shutdown_flush_finished",
    "background_tasks.cancelled",
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


def _fingerprint(text: Any) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _message_shape(message: dict[str, Any], index: int) -> dict[str, Any]:
    text = str(message.get("text", "") or "")
    role = str(message.get("role", "unknown") or "unknown")[:40]
    row = {
        "kind": "buffer_message",
        "index": index,
        "timestamp": _safe_float(message.get("ts", 0.0)),
        "role": role,
        "text_chars": len(text),
        "text_fingerprint": _fingerprint(text),
    }
    if role == "group_observed":
        row["sender_fingerprint"] = _fingerprint(message.get("sender_id", ""))
    return row


def _event_action(event_type: str) -> str:
    if event_type == "prompt.injection_assembled":
        return "prompt_injection"
    if event_type == "tool.invocation_started":
        return "tool_started"
    if event_type == "tool.invocation_finished":
        return "tool_finished"
    if event_type == "response.observed":
        return "response_observed"
    if event_type == "reasoning.trace_snapshot":
        return "reasoning_trace_viewed"
    if event_type.endswith("_snapshot"):
        return event_type.replace(".", "_")
    return event_type.replace(".", "_")[:120]


def _event_shape(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("type", "") or "runtime.event")
    shape: dict[str, Any] = {
        "kind": "runtime_event",
        "id": _safe_int(event.get("id", 0)),
        "timestamp": _safe_float(event.get("ts", 0.0)),
        "type": event_type[:120],
        "action": _event_action(event_type),
        "severity": str(event.get("severity", "") or "info")[:40],
        "source": str(event.get("source", "") or "")[:120],
        "tags": list(event.get("tags", []) or [])[:12],
        "payload_keys": sorted(str(key)[:80] for key in payload.keys())[:25],
    }
    if event_type == "prompt.injection_assembled":
        shape["evidence"] = {
            "budget_chars": _safe_int(payload.get("budget_chars", 0)),
            "injection_path": str(payload.get("injection_path", "") or "")[:80],
            "injected_slots": list(payload.get("injected_slots", []) or [])[:12],
            "skipped_slots": list(payload.get("skipped_slots", []) or [])[:12],
        }
    elif event_type.startswith("tool.invocation"):
        shape["evidence"] = {
            "tool_name": str(payload.get("tool_name", "") or "")[:120],
            "arg_keys": list(payload.get("arg_keys", []) or [])[:20],
            "arg_chars": _safe_int(payload.get("arg_chars", 0)),
            "result_chars": _safe_int(payload.get("result_chars", 0)),
            "success": payload.get("success"),
        }
    elif event_type == "response.observed":
        shape["evidence"] = {
            "text_chars": _safe_int(payload.get("text_chars", payload.get("text_len", 0))),
            "flags": list(payload.get("flags", []) or [])[:12],
            "confidence": _safe_float(payload.get("confidence", 0.0)),
        }
    elif event_type == "memory.recall_performed":
        shape["evidence"] = {
            "query_chars": _safe_int(payload.get("query_chars", 0)),
            "gap_seconds": _safe_float(payload.get("gap_seconds", 0.0)),
            "recall_limit": _safe_int(payload.get("recall_limit", 0)),
            "result_count": _safe_int(payload.get("result_count", 0)),
            "l2_recalled_count": _safe_int(payload.get("l2_recalled_count", 0)),
        }
    else:
        shape["evidence"] = {
            key: value
            for key, value in payload.items()
            if isinstance(value, (bool, int, float))
        }
    return shape


def _buffer_timeline(plugin: Any, session_key: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    buffers = getattr(plugin, "_conversation_buffers", {}) or {}
    buf = buffers.get(session_key) if hasattr(buffers, "get") else None
    messages = list(getattr(buf, "messages", []) or []) if buf is not None else []
    shaped = [
        _message_shape(message, index)
        for index, message in enumerate(messages[-limit:])
        if isinstance(message, dict)
    ]
    roles = Counter(row.get("role", "unknown") for row in shaped)
    meta = {
        "has_buffer": buf is not None,
        "buffer_messages": len(messages),
        "buffer_turn_count": _safe_int(getattr(buf, "turn_count", 0)) if buf is not None else 0,
        "last_activity": _safe_float(getattr(buf, "last_activity", 0.0)) if buf is not None else 0.0,
        "last_flush_ts": _safe_float(getattr(buf, "last_flush_ts", 0.0)) if buf is not None else 0.0,
        "roles": dict(roles),
    }
    return shaped, meta


def _session_keys(plugin: Any, requested: str = "") -> list[str]:
    if requested:
        return [requested]
    keys: set[str] = set()
    for attr in (
        "_hosts",
        "_conversation_buffers",
        "_memory_systems",
        "_prompt_debug_snapshots",
        "_last_request_budgets",
    ):
        mapping = getattr(plugin, attr, None)
        if hasattr(mapping, "keys"):
            keys.update(str(key) for key in mapping.keys())
    bus = getattr(plugin, "_runtime_event_bus", None)
    if bus is not None and hasattr(bus, "recent"):
        for event in bus.recent(limit=300):
            if isinstance(event, dict) and event.get("session_key"):
                keys.add(str(event.get("session_key")))
    return sorted(keys)


def build_session_replay_snapshot(
    plugin: Any, *, session_key: str = "", limit: int = 80
) -> dict[str, Any]:
    """Build redacted replay timelines for recent session activity.

    This intentionally replays metadata only. It never exposes user text,
    bot text, prompt bodies, tool argument values, tool results, or memory
    bodies, and it does not mutate the session state.
    """
    limit = max(1, min(300, int(limit or 80)))
    bus = getattr(plugin, "_runtime_event_bus", None)
    sessions: list[dict[str, Any]] = []
    total_events = 0
    total_buffer_messages = 0

    for key in _session_keys(plugin, session_key)[:50]:
        events: list[dict[str, Any]] = []
        if bus is not None and hasattr(bus, "recent"):
            events = [
                event
                for event in bus.recent(limit=limit * 2, session_key=key)
                if isinstance(event, dict)
                and str(event.get("type", "")) in _REPLAY_EVENT_TYPES
            ][:limit]
        event_steps = [_event_shape(event) for event in events]
        buffer_steps, buffer_meta = _buffer_timeline(plugin, key, limit)
        timeline = sorted(
            event_steps + buffer_steps,
            key=lambda item: (float(item.get("timestamp") or 0.0), str(item.get("kind") or "")),
        )[-limit:]
        by_kind = Counter(str(item.get("kind") or "unknown") for item in timeline)
        by_action = Counter(str(item.get("action") or item.get("role") or "unknown") for item in timeline)
        total_events += len(event_steps)
        total_buffer_messages += int(buffer_meta.get("buffer_messages", 0) or 0)
        sessions.append({
            "session_key": key,
            "summary": {
                "timeline_items": len(timeline),
                "runtime_events": len(event_steps),
                "buffer_messages": buffer_meta.get("buffer_messages", 0),
                "buffer_turn_count": buffer_meta.get("buffer_turn_count", 0),
                "by_kind": dict(by_kind),
                "by_action": dict(by_action.most_common(12)),
                "roles": buffer_meta.get("roles", {}),
                "last_activity": buffer_meta.get("last_activity", 0.0),
                "last_flush_ts": buffer_meta.get("last_flush_ts", 0.0),
            },
            "timeline": timeline,
        })

    return {
        "schema": SESSION_REPLAY_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "messages": "message text omitted; role, length, timestamp, and fingerprint only",
            "events": "runtime event payload values omitted except non-sensitive counters/status",
            "tools": "tool argument values and results omitted",
        },
        "summary": {
            "sessions": len(sessions),
            "session_filter": session_key,
            "runtime_events": total_events,
            "buffer_messages": total_buffer_messages,
        },
        "sessions": sessions,
    }
