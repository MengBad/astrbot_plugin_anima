"""Redacted Scar Explorer snapshots for the Cognitive Observatory."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any


SCAR_EXPLORER_SCHEMA = "anima.scar_explorer.v1"

_SYLANNE_DIM_NAMES = (
    "warmth",
    "arousal",
    "valence",
    "tension",
    "curiosity",
    "repair_pressure",
    "expression_drive",
    "boundary_firmness",
)

_LEGACY_DIM_NAMES = (
    "warmth",
    "arousal",
    "trust_breach",
    "rejection",
    "curiosity",
    "being_replaced",
    "abandonment",
    "identity_denial",
)


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


def _stage_name(stage: Any) -> str:
    if hasattr(stage, "name"):
        return str(stage.name)
    return str(stage or "UNKNOWN")


def _scar_payload(scar: Any) -> dict[str, Any]:
    dimension = _safe_int(getattr(scar, "dimension", 0))
    return {
        "dimension": dimension,
        "dimension_name": _SYLANNE_DIM_NAMES[dimension]
        if 0 <= dimension < len(_SYLANNE_DIM_NAMES)
        else f"dim_{dimension}",
        "stage": _stage_name(getattr(scar, "stage", "")),
        "ticks_in_stage": _safe_int(getattr(scar, "ticks_in_stage", 0)),
        "timestamp": _clamp_float(getattr(scar, "timestamp", 0.0)),
        "alpha": _clamp_float(getattr(scar, "alpha", 0.0)),
    }


def _dimension_payload(scar_state: Any) -> list[dict[str, Any]]:
    scars = list(getattr(scar_state, "scars", []) or [])
    by_dim = Counter(_safe_int(getattr(scar, "dimension", 0)) for scar in scars)
    return [
        {
            "dimension": dim,
            "name": _SYLANNE_DIM_NAMES[dim]
            if dim < len(_SYLANNE_DIM_NAMES)
            else f"dim_{dim}",
            "base": _clamp_float((getattr(scar_state, "base", []) or [])[dim])
            if dim < len(getattr(scar_state, "base", []) or [])
            else 0.0,
            "sensitivity": _clamp_float(scar_state.modifier(dim))
            if hasattr(scar_state, "modifier")
            else 1.0,
            "scar_count": int(by_dim.get(dim, 0)),
            "density": _clamp_float(scar_state.scar_density(dim))
            if hasattr(scar_state, "scar_density")
            else 0.0,
            "numbed": bool(scar_state.is_numbed(dim))
            if hasattr(scar_state, "is_numbed")
            else False,
        }
        for dim in range(_safe_int(getattr(scar_state, "n_dims", len(_SYLANNE_DIM_NAMES)), len(_SYLANNE_DIM_NAMES)))
    ]


def _host_payload(session_key: str, host: Any, *, limit: int) -> dict[str, Any] | None:
    kernel = getattr(host, "kernel", None)
    comp = getattr(kernel, "computation", None)
    engine = getattr(comp, "engine", None)
    scar_state = getattr(engine, "scar_state", None)
    if scar_state is None:
        return None

    scars = list(getattr(scar_state, "scars", []) or [])
    stage_counts = Counter(_stage_name(getattr(scar, "stage", "")) for scar in scars)
    recent_scars = sorted(
        scars,
        key=lambda scar: float(getattr(scar, "timestamp", 0.0) or 0.0),
        reverse=True,
    )[:limit]
    return {
        "session_key": session_key,
        "source": "sylanne_host",
        "tick": _safe_int(getattr(scar_state, "_tick", 0)),
        "total_scars": len(scars),
        "n_dims": _safe_int(getattr(scar_state, "n_dims", 0)),
        "wound_threshold": _clamp_float(getattr(scar_state, "wound_threshold", 0.0)),
        "session_scar_count": _safe_int(getattr(scar_state, "_session_scar_count", 0)),
        "session_scar_cap": _safe_int(getattr(scar_state, "_session_scar_cap", 0)),
        "circuit_breaker_active": bool(getattr(scar_state, "_circuit_breaker_active", False)),
        "circuit_breaker_remaining": _safe_int(getattr(scar_state, "_circuit_breaker_remaining", 0)),
        "recent_scar_tick_count": len(getattr(scar_state, "_recent_scar_ticks", []) or []),
        "last_step_time": _clamp_float(getattr(scar_state, "_last_step_time", 0.0)),
        "stage_counts": dict(stage_counts),
        "dimensions": _dimension_payload(scar_state),
        "recent_scars": [_scar_payload(scar) for scar in recent_scars],
    }


def _legacy_payload(plugin: Any) -> dict[str, Any]:
    path = getattr(plugin, "scar_dimensions_path", None)
    data: dict[str, Any] = {}
    if path and hasattr(plugin, "_read_json"):
        data = plugin._read_json(path, default={}) or {}
    elif hasattr(plugin, "_read_scar_dimensions"):
        data = plugin._read_scar_dimensions() or {}
    if not isinstance(data, dict):
        data = {}

    dimensions = []
    for name in _LEGACY_DIM_NAMES:
        item = data.get(name, {})
        if not isinstance(item, dict):
            item = {}
        dimensions.append({
            "name": name,
            "count": _safe_int(item.get("count", 0)),
            "sensitivity": _clamp_float(item.get("sensitivity", 1.0), 1.0),
            "last_triggered": str(item.get("last_triggered", "") or ""),
        })
    return {
        "source": "legacy_json",
        "configured": bool(path),
        "dimension_count": len(data),
        "total_scars": sum(item["count"] for item in dimensions),
        "dimensions": dimensions,
    }


def build_scar_explorer_snapshot(plugin: Any, *, session_key: str = "", limit: int = 8) -> dict[str, Any]:
    """Build a scar topology snapshot without mutating scar state or creating hosts."""
    limit = max(1, min(30, int(limit or 8)))
    hosts = getattr(plugin, "_hosts", {}) or {}
    sessions: list[str] = []
    if hasattr(hosts, "keys"):
        sessions = sorted(str(key) for key in hosts.keys())
    if session_key:
        sessions = [key for key in sessions if key == session_key]

    sylanne_sessions: list[dict[str, Any]] = []
    for key in sessions:
        host = hosts.get(key) if hasattr(hosts, "get") else None
        if host is None:
            continue
        payload = _host_payload(key, host, limit=limit)
        if payload is not None:
            sylanne_sessions.append(payload)

    legacy = _legacy_payload(plugin)
    has_sylanne = bool(sylanne_sessions)
    has_legacy = bool(legacy.get("dimension_count") or legacy.get("total_scars"))
    if has_sylanne and has_legacy:
        topology = "dual_source"
    elif has_sylanne:
        topology = "sylanne_only"
    elif has_legacy:
        topology = "legacy_only"
    else:
        topology = "empty"

    return {
        "schema": SCAR_EXPLORER_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "scar_events": "scar event source text omitted; dimensions/stages/timestamps only",
            "legacy": "legacy dimensions contain no raw message text",
        },
        "summary": {
            "topology": topology,
            "sylanne_sessions": len(sylanne_sessions),
            "sylanne_total_scars": sum(item["total_scars"] for item in sylanne_sessions),
            "legacy_total_scars": legacy.get("total_scars", 0),
            "active_circuit_breakers": sum(
                1 for item in sylanne_sessions if item.get("circuit_breaker_active")
            ),
            "session_cap_pressure": sum(
                1
                for item in sylanne_sessions
                if item.get("session_scar_cap")
                and item.get("session_scar_count", 0) >= item.get("session_scar_cap", 0)
            ),
        },
        "sessions": sylanne_sessions,
        "legacy": legacy,
    }
