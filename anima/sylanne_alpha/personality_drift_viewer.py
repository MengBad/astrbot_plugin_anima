"""Redacted Personality Drift Viewer snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any


PERSONALITY_DRIFT_VIEWER_SCHEMA = "anima.personality_drift_viewer.v1"

_LEGACY_TRAITS = (
    "expressiveness",
    "sensitivity",
    "boundary_permeability",
    "order_sense",
    "relationship_gravity",
)

_EMBODIMENT_TRAITS = (
    "expression_drive_trait",
    "perception_acuity",
    "boundary_permeability",
    "inner_order",
    "relational_gravity",
)

_SYLANNE_TRAITS = (
    "warmth_bias",
    "edge",
    "curiosity",
    "patience",
    "intimacy_gravity",
    "sovereignty_guard",
)


def _fingerprint(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def _clamp_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _trait_memory_payload(name: str, memory: Any) -> dict[str, Any]:
    value = _clamp_float(getattr(memory, "value", 0.5), 0.5)
    set_point = _clamp_float(getattr(memory, "set_point", value), value)
    return {
        "name": name,
        "value": value,
        "fast_ema": _clamp_float(getattr(memory, "fast_ema", 0.0)),
        "slow_ema": _clamp_float(getattr(memory, "slow_ema", 0.0)),
        "set_point": set_point,
        "distance_from_set_point": round(value - set_point, 4),
        "frozen": bool(getattr(memory, "frozen", False)),
    }


def _drift_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    trigger = str(event.get("trigger", "") or "")
    dimension = str(event.get("dimension", "") or "")
    return {
        "timestamp": _clamp_float(event.get("timestamp", 0.0)),
        "trigger": trigger[:64],
        "trigger_fingerprint": _fingerprint(trigger),
        "dimension": dimension[:64],
        "delta": _clamp_float(event.get("delta", 0.0)),
        "value": _clamp_float(event.get("value", 0.0)),
    }


def _mutation_payload(item: Any) -> dict[str, Any]:
    data = dict(item or {}) if isinstance(item, dict) else {}
    desc = str(data.get("desc") or data.get("description") or data.get("mutation") or "")
    return {
        "type": str(data.get("type") or data.get("mtype") or "")[:64],
        "triggered_by": str(data.get("triggered_by") or "")[:64],
        "timestamp": str(data.get("timestamp") or data.get("time") or "")[:64],
        "description_chars": len(desc),
        "description_fingerprint": _fingerprint(desc),
    }


def _legacy_vector(plugin: Any) -> dict[str, float]:
    pv = getattr(plugin, "_personality_vector", None)
    if not isinstance(pv, dict) and hasattr(plugin, "_load_state"):
        try:
            state = plugin._load_state() or {}
            pv = state.get("personality_vector")
        except Exception:
            pv = None
    if not isinstance(pv, dict):
        pv = {}
    return {name: _clamp_float(pv.get(name, 0.5), 0.5) for name in _LEGACY_TRAITS}


def _mutation_history(plugin: Any, *, limit: int) -> list[dict[str, Any]]:
    state: dict[str, Any] = {}
    if hasattr(plugin, "_load_state"):
        try:
            state = plugin._load_state() or {}
        except Exception:
            state = {}
    history = state.get("mutation_history", []) if isinstance(state, dict) else []
    if not isinstance(history, list):
        history = []
    return [_mutation_payload(item) for item in history[-limit:]]


def _persona_core_info(plugin: Any) -> dict[str, Any]:
    path = getattr(plugin, "persona_core_path", None)
    if not path:
        return {"configured": False, "exists": False}
    info: dict[str, Any] = {
        "configured": True,
        "exists": False,
        "path": os.path.basename(str(path)),
    }
    try:
        if not os.path.exists(path):
            return info
        stat = os.stat(path)
        info.update({
            "exists": True,
            "size_bytes": int(stat.st_size),
            "mtime": float(stat.st_mtime),
        })
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        info.update({
            "content_chars": len(text),
            "content_fingerprint": _fingerprint(text),
        })
    except Exception as exc:
        info["error"] = type(exc).__name__
    return info


def _session_payload(session_key: str, host: Any, *, limit: int) -> dict[str, Any] | None:
    kernel = getattr(host, "kernel", None)
    comp = getattr(kernel, "computation", None)
    if comp is None:
        return None

    personality = dict(getattr(comp, "_personality", {}) or {})
    embodiment = getattr(comp, "_embodiment_traits", {}) or {}
    attribution = getattr(comp, "_drift_attribution", None)
    events = attribution.recent(limit) if hasattr(attribution, "recent") else []
    relationship_deltas = getattr(comp, "_relationship_deltas", {}) or {}
    rel_count = len(relationship_deltas) if hasattr(relationship_deltas, "__len__") else 0

    return {
        "session_key": session_key,
        "source": "sylanne_host",
        "tick": _safe_int(getattr(comp, "_tick_count", 0)),
        "drift_tick": _safe_int(getattr(comp, "_drift_tick", 0)),
        "last_drift_time": _clamp_float(getattr(comp, "_last_drift_time", 0.0)),
        "drift_min_interval": _clamp_float(getattr(comp, "_drift_min_interval", 0.0)),
        "personality_dirty": bool(getattr(comp, "_personality_dirty", False)),
        "relationship_delta_sessions": rel_count,
        "sylanne_traits": {
            name: _clamp_float(personality.get(name, personality.get(name, 0.5)), 0.5)
            for name in _SYLANNE_TRAITS
            if name in personality
        },
        "legacy_compat_traits": {
            name: _clamp_float(personality.get(name, 0.5), 0.5)
            for name in ("extraversion", "neuroticism", "openness", "conscientiousness", "agreeableness")
            if name in personality
        },
        "embodiment_traits": [
            _trait_memory_payload(name, embodiment[name])
            for name in _EMBODIMENT_TRAITS
            if name in embodiment
        ],
        "recent_drift_events": [
            _drift_event_payload(event)
            for event in list(events)[-limit:]
            if isinstance(event, dict)
        ],
    }


def build_personality_drift_viewer_snapshot(
    plugin: Any, *, session_key: str = "", limit: int = 12
) -> dict[str, Any]:
    """Build a redacted personality continuity snapshot without creating sessions."""
    limit = max(1, min(50, int(limit or 12)))
    hosts = getattr(plugin, "_hosts", {}) or {}
    sessions = sorted(str(key) for key in hosts.keys()) if hasattr(hosts, "keys") else []
    if session_key:
        sessions = [key for key in sessions if key == session_key]

    session_payloads: list[dict[str, Any]] = []
    for key in sessions:
        host = hosts.get(key) if hasattr(hosts, "get") else None
        if host is None:
            continue
        payload = _session_payload(key, host, limit=limit)
        if payload is not None:
            session_payloads.append(payload)

    mutation_history = _mutation_history(plugin, limit=limit)
    legacy_vector = _legacy_vector(plugin)
    return {
        "schema": PERSONALITY_DRIFT_VIEWER_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "persona_core": "content omitted; size and sha256 fingerprint only",
            "mutations": "mutation descriptions omitted; lengths and sha256 fingerprints only",
            "drift_events": "numeric drift attribution retained; raw message text omitted",
        },
        "summary": {
            "sylanne_sessions": len(session_payloads),
            "legacy_vector_available": bool(legacy_vector),
            "mutation_history_count": len(mutation_history),
            "active_dirty_sessions": sum(1 for item in session_payloads if item.get("personality_dirty")),
            "relationship_delta_sessions": sum(
                int(item.get("relationship_delta_sessions", 0) or 0)
                for item in session_payloads
            ),
            "recent_drift_events": sum(
                len(item.get("recent_drift_events", []) or [])
                for item in session_payloads
            ),
        },
        "legacy": {
            "personality_vector": legacy_vector,
            "mutation_history": mutation_history,
            "persona_core": _persona_core_info(plugin),
            "config": {
                "persona_lock": bool(getattr(plugin, "config", {}).get("persona_lock", False))
                if isinstance(getattr(plugin, "config", None), dict)
                else False,
                "danger_core_mutation": bool(getattr(plugin, "config", {}).get("danger_core_mutation", False))
                if isinstance(getattr(plugin, "config", None), dict)
                else False,
            },
        },
        "sessions": session_payloads,
    }
