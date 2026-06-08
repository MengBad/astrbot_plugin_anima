"""Redacted Memory Recall Replay snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from typing import Any


MEMORY_RECALL_REPLAY_SCHEMA = "anima.memory_recall_replay.v1"

_RECALL_EVENT_TYPES = {
    "memory.recall_performed",
    "memory.explorer_snapshot",
    "prompt.injection_assembled",
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


def _fingerprint(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _item_payload(item: Any, *, layer: str = "L2") -> dict[str, Any]:
    data = item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
    text = str(data.get("text", "") or "")
    return {
        "layer": layer,
        "id": str(data.get("id", "") or "")[:16],
        "text_chars": len(text),
        "text_fingerprint": _fingerprint(text),
        "weight": _safe_float(data.get("weight", 0.0)),
        "temperature": _safe_float(data.get("temperature", 0.0)),
        "age_ticks": _safe_int(data.get("age_ticks", 0)),
        "created_at": _safe_float(data.get("created_at", 0.0)),
        "confirmed": bool(data.get("confirmed", False)),
        "recall_count": _safe_int(data.get("recall_count", 0)),
        "last_recalled_tick": _safe_int(data.get("last_recalled_tick", 0)),
        "rewrite_count": _safe_int(data.get("rewrite_count", 0)),
        "has_embedding": bool(data.get("embedding")),
    }


def _memory_system_shape(memory_system: Any, *, limit: int) -> dict[str, Any]:
    l1 = list(getattr(memory_system, "_l1", []) or [])
    l2 = list(getattr(memory_system, "_l2", []) or [])
    l3_nodes = dict(getattr(memory_system, "_l3_nodes", {}) or {})
    l3_edges = list(getattr(memory_system, "_l3_edges", []) or [])
    recalled = list(getattr(memory_system, "_recalled_l2_items", []) or [])
    params = dict(getattr(memory_system, "_params", {}) or {})
    recalled_payloads = [
        _item_payload(item, layer="L2")
        for item in sorted(
            recalled,
            key=lambda row: int(getattr(row, "last_recalled_tick", 0) or 0),
            reverse=True,
        )[:limit]
    ]
    return {
        "tick": _safe_int(getattr(memory_system, "_tick", 0)),
        "counts": {
            "l1_hot": len(l1),
            "l2_warm": len(l2),
            "l3_nodes": len(l3_nodes),
            "l3_edges": len(l3_edges),
            "recalled_l2": len(recalled),
            "embedding_items": sum(1 for item in [*l1, *l2] if bool(getattr(item, "embedding", None))),
        },
        "params": {
            key: _safe_float(params.get(key, 0.0))
            for key in (
                "base_decay",
                "reconsolidation_rate",
                "compression_threshold",
                "mood_weight",
                "positive_recall_bias",
                "recall_boost",
            )
        },
        "last_recalled_l2": recalled_payloads,
    }


def _prompt_snapshot_shape(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw_lengths = snapshot.get("raw_lengths") if isinstance(snapshot.get("raw_lengths"), dict) else {}
    trimmed_lengths = snapshot.get("trimmed_lengths") if isinstance(snapshot.get("trimmed_lengths"), dict) else {}
    return {
        "timestamp": _safe_float(snapshot.get("timestamp", 0.0)),
        "session_key": str(snapshot.get("session_key", "") or "")[:240],
        "budget_chars": _safe_int(snapshot.get("budget_chars", 0)),
        "gap_seconds": _safe_float(snapshot.get("gap_seconds", 0.0)),
        "injection_path": str(snapshot.get("injection_path", "") or "")[:80],
        "memory_raw_chars": _safe_int(raw_lengths.get("memory", 0)),
        "memory_trimmed_chars": _safe_int(trimmed_lengths.get("memory", 0)),
        "memory_injected": "memory" in trimmed_lengths,
        "memory_skipped": "memory" in raw_lengths and "memory" not in trimmed_lengths,
        "injected_slots": [str(slot)[:80] for slot in list(snapshot.get("injected_slots") or [])[:12]],
        "skipped_slots": [str(slot)[:80] for slot in list(snapshot.get("skipped_slots") or [])[:12]],
    }


def _prompt_snapshots(plugin: Any, session_key: str, limit: int) -> list[dict[str, Any]]:
    snapshots = getattr(plugin, "_prompt_debug_snapshots", {}) or {}
    values = list(snapshots.values()) if hasattr(snapshots, "values") else []
    rows = [
        _prompt_snapshot_shape(item)
        for item in values
        if isinstance(item, dict)
        and (not session_key or str(item.get("session_key", "") or "") == session_key)
    ]
    rows.sort(key=lambda item: float(item.get("timestamp") or 0.0), reverse=True)
    return rows[:limit]


def _event_shape(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("type", "") or "unknown")
    evidence: dict[str, Any] = {}
    if event_type == "memory.recall_performed":
        layer_counts = payload.get("layer_counts") if isinstance(payload.get("layer_counts"), dict) else {}
        reason_counts = payload.get("reason_counts") if isinstance(payload.get("reason_counts"), dict) else {}
        evidence = {
            "query_chars": _safe_int(payload.get("query_chars", 0)),
            "query_fingerprint": str(payload.get("query_fingerprint", "") or "")[:40],
            "gap_seconds": _safe_float(payload.get("gap_seconds", 0.0)),
            "recall_limit": _safe_int(payload.get("recall_limit", 0)),
            "result_count": _safe_int(payload.get("result_count", 0)),
            "l2_recalled_count": _safe_int(payload.get("l2_recalled_count", 0)),
            "layer_counts": {
                str(k)[:40]: _safe_int(v)
                for k, v in list(layer_counts.items())[:10]
            },
            "reason_counts": {
                str(k)[:80]: _safe_int(v)
                for k, v in list(reason_counts.items())[:10]
            },
        }
    elif event_type == "prompt.injection_assembled":
        evidence = {
            "budget_chars": _safe_int(payload.get("budget_chars", 0)),
            "injection_path": str(payload.get("injection_path", "") or "")[:80],
            "injected_slots": [str(slot)[:80] for slot in list(payload.get("injected_slots") or [])[:12]],
            "skipped_slots": [str(slot)[:80] for slot in list(payload.get("skipped_slots") or [])[:12]],
        }
    else:
        evidence = {
            key: value
            for key, value in payload.items()
            if isinstance(value, (bool, int, float))
        }
    return {
        "id": _safe_int(event.get("id", 0)),
        "ts": _safe_float(event.get("ts", 0.0)),
        "type": event_type[:120],
        "source": str(event.get("source", "") or "")[:120],
        "severity": str(event.get("severity", "") or "info")[:40],
        "tags": [str(tag)[:80] for tag in list(event.get("tags") or [])[:8]],
        "evidence": evidence,
    }


def _recent_events(plugin: Any, session_key: str, limit: int) -> list[dict[str, Any]]:
    bus = getattr(plugin, "_runtime_event_bus", None)
    if bus is None or not hasattr(bus, "recent"):
        return []
    try:
        events = bus.recent(limit=max(20, min(1000, limit * 3)), session_key=session_key)
    except Exception:
        return []
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("type", "") or "") not in _RECALL_EVENT_TYPES:
            continue
        rows.append(_event_shape(event))
        if len(rows) >= limit:
            break
    return rows


def _session_keys(plugin: Any, requested: str = "") -> list[str]:
    if requested:
        return [requested]
    keys: set[str] = set()
    for attr in ("_memory_systems", "_prompt_debug_snapshots", "_conversation_buffers", "_hosts"):
        mapping = getattr(plugin, attr, None)
        if hasattr(mapping, "keys"):
            keys.update(str(key) for key in mapping.keys())
    if getattr(plugin, "_memory_system", None) is not None:
        keys.add("default")
    bus = getattr(plugin, "_runtime_event_bus", None)
    if bus is not None and hasattr(bus, "recent"):
        try:
            for event in bus.recent(limit=300):
                if isinstance(event, dict) and str(event.get("type", "") or "") in _RECALL_EVENT_TYPES:
                    if event.get("session_key"):
                        keys.add(str(event.get("session_key")))
        except Exception:
            pass
    return sorted(keys)


def build_memory_recall_replay_snapshot(
    plugin: Any, *, session_key: str = "", limit: int = 50
) -> dict[str, Any]:
    """Build a redacted replay of recent memory recall evidence.

    The snapshot is read-only. It never calls ``recall()``, never mutates memory
    weights, and never exposes memory text, query text, prompt bodies, graph
    labels, or arbitrary runtime-event payload values.
    """
    limit = max(1, min(200, int(limit or 50)))
    memory_systems = getattr(plugin, "_memory_systems", {}) or {}
    sessions: list[dict[str, Any]] = []
    total_recalled = 0
    total_events = 0
    total_memory_injections = 0

    for key in _session_keys(plugin, session_key)[:50]:
        system = memory_systems.get(key) if hasattr(memory_systems, "get") else None
        if system is None and key == "default":
            system = getattr(plugin, "_memory_system", None)
        memory_shape = _memory_system_shape(system, limit=limit) if system is not None else {
            "tick": 0,
            "counts": {
                "l1_hot": 0,
                "l2_warm": 0,
                "l3_nodes": 0,
                "l3_edges": 0,
                "recalled_l2": 0,
                "embedding_items": 0,
            },
            "params": {},
            "last_recalled_l2": [],
        }
        prompt_rows = _prompt_snapshots(plugin, key, limit=limit)
        event_rows = _recent_events(plugin, key, limit=limit)
        event_counts = Counter(str(item.get("type") or "unknown") for item in event_rows)
        memory_injections = sum(1 for item in prompt_rows if bool(item.get("memory_injected")))
        total_recalled += int(memory_shape["counts"].get("recalled_l2", 0) or 0)
        total_events += len(event_rows)
        total_memory_injections += memory_injections
        sessions.append({
            "session_key": key,
            "summary": {
                "has_memory_system": system is not None,
                "recalled_l2": memory_shape["counts"].get("recalled_l2", 0),
                "recall_events": event_counts.get("memory.recall_performed", 0),
                "prompt_snapshots": len(prompt_rows),
                "memory_injections": memory_injections,
                "memory_skips": sum(1 for item in prompt_rows if bool(item.get("memory_skipped"))),
            },
            "memory": memory_shape,
            "prompt_injections": prompt_rows,
            "events": event_rows,
        })

    return {
        "schema": MEMORY_RECALL_REPLAY_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "memory": "memory text omitted; length and sha256 fingerprints only",
            "query": "query text omitted; query length and sha256 fingerprint only",
            "prompt": "prompt bodies omitted; slot lengths and budget metadata only",
            "events": "runtime payloads are whitelisted to recall and budget metadata",
        },
        "summary": {
            "sessions": len(sessions),
            "session_filter": session_key,
            "recalled_l2": total_recalled,
            "recall_events": total_events,
            "memory_injections": total_memory_injections,
        },
        "sessions": sessions,
    }
