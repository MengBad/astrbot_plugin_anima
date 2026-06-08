"""Redacted Desire Evolution History snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any


DESIRE_EVOLUTION_SCHEMA = "anima.desire_evolution_history.v1"

_DESIRE_EVENT_TYPES = {
    "desire.queue_updated",
    "desire.dashboard_snapshot",
    "desire.evolution_snapshot",
}

_SAFE_EVENT_KEYS = {
    "before_count",
    "after_count",
    "before_active_count",
    "after_active_count",
    "before_satisfied_count",
    "after_satisfied_count",
    "added_content_fingerprints",
    "removed_content_fingerprints",
    "by_source",
    "by_kind",
    "total",
    "active",
    "satisfied",
    "scoped_to_umo",
    "global_or_legacy",
    "missing_content",
    "max_queue",
    "queue_fill_ratio",
}


def _fingerprint(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _desire_kind(desire: dict[str, Any]) -> str:
    kind = str(desire.get("kind", "") or "")
    if kind in ("inward", "outward"):
        return kind
    source = str(desire.get("source", "") or "")
    if source in {"info_collection", "relationship", "memory_infection"}:
        return "outward"
    return "inward"


def _bucket_intensity(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.3:
        return "medium"
    return "low"


def _counter_inc(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _desire_payload(desire: dict[str, Any], now: float) -> dict[str, Any]:
    content = str(desire.get("content", "") or "")
    created_at = _parse_ts(desire.get("created_at"))
    intensity = _float(desire.get("intensity", 0.0))
    target_umo = str(desire.get("target_umo", "") or "")
    target_user = str(desire.get("target_user", "") or "")
    return {
        "id": str(desire.get("id", "") or "")[:24],
        "content_chars": len(content),
        "content_fingerprint": _fingerprint(content),
        "source": str(desire.get("source", "") or "unknown"),
        "kind": _desire_kind(desire),
        "intensity": intensity,
        "intensity_bucket": _bucket_intensity(intensity),
        "satisfied": bool(desire.get("satisfied", False)),
        "created_at_ts": created_at,
        "age_seconds": round(max(0.0, now - created_at), 3) if created_at else 0.0,
        "has_target_umo": bool(target_umo),
        "target_umo_hash": _fingerprint(target_umo),
        "has_target_user": bool(target_user),
        "target_user_hash": _fingerprint(target_user),
        "repeat_count": int(desire.get("repeat_count", 0) or 0),
        "max_repeats": int(desire.get("max_repeats", 0) or 0),
    }


def _safe_event_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in _SAFE_EVENT_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            safe[key] = value
        elif isinstance(value, dict):
            safe[key] = {
                str(k)[:80]: int(v) if isinstance(v, bool) is False and isinstance(v, int) else v
                for k, v in list(value.items())[:20]
                if isinstance(v, (bool, int, float))
            }
        elif isinstance(value, list):
            safe[key] = [
                str(item)[:40]
                for item in value[:20]
                if isinstance(item, (str, int, float))
            ]
    return safe


def _timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    safe_payload = _safe_event_payload(payload)
    return {
        "id": int(event.get("id") or 0),
        "ts": _float(event.get("ts", 0.0)),
        "type": str(event.get("type", "") or "unknown")[:120],
        "source": str(event.get("source", "") or "")[:120],
        "severity": str(event.get("severity", "") or "info")[:40],
        "tags": [str(tag)[:80] for tag in list(event.get("tags") or [])[:8]],
        "payload_keys": sorted(str(key)[:80] for key in safe_payload.keys())[:24],
        "evidence": safe_payload,
    }


def _recent_desire_events(plugin: Any, limit: int) -> list[dict[str, Any]]:
    bus = getattr(plugin, "_runtime_event_bus", None)
    if bus is None or not hasattr(bus, "recent"):
        return []
    try:
        events = bus.recent(limit=max(20, min(1000, limit * 3)))
    except Exception:
        return []
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("type", "") or "") not in _DESIRE_EVENT_TYPES:
            continue
        rows.append(_timeline_event(event))
        if len(rows) >= limit:
            break
    return rows


def build_desire_evolution_snapshot(plugin: Any, *, limit: int = 80) -> dict[str, Any]:
    """Build a redacted history view of desire queue evolution.

    The snapshot is read-only and intentionally does not expose desire text,
    target identifiers, or raw runtime-event payload values outside a narrow
    whitelist of counts, buckets, and pre-redacted fingerprints.
    """
    limit = max(1, min(200, int(limit or 80)))
    try:
        desires = plugin._read_desires() if hasattr(plugin, "_read_desires") else []
    except Exception:
        desires = []
    if not isinstance(desires, list):
        desires = []

    now = time.time()
    current_desires: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_intensity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    satisfied = 0
    scoped = 0
    missing_content = 0

    for raw in desires:
        if not isinstance(raw, dict):
            continue
        payload = _desire_payload(raw, now)
        current_desires.append(payload)
        _counter_inc(by_source, payload["source"])
        _counter_inc(by_kind, payload["kind"])
        _counter_inc(by_intensity, payload["intensity_bucket"])
        if payload["satisfied"]:
            satisfied += 1
        if payload["has_target_umo"]:
            scoped += 1
        if not payload["content_chars"]:
            missing_content += 1

    current_desires.sort(
        key=lambda item: (bool(item.get("satisfied")), -float(item.get("intensity", 0.0)), -float(item.get("created_at_ts", 0.0)))
    )
    timeline = _recent_desire_events(plugin, limit)
    event_counts = Counter(str(item.get("type") or "unknown") for item in timeline)
    config = getattr(plugin, "_config", None) or getattr(plugin, "config", {}) or {}
    total = len(current_desires)
    active = max(0, total - satisfied)

    return {
        "schema": DESIRE_EVOLUTION_SCHEMA,
        "timestamp": now,
        "redaction": {
            "content": "omitted; content length and sha256 fingerprints only",
            "targets": "UMO and user identifiers omitted; sha256 fingerprints only",
            "events": "raw runtime payloads omitted; whitelisted counts and fingerprints only",
        },
        "summary": {
            "enabled": bool(config.get("desire_enabled", False)),
            "total_current": total,
            "active_current": active,
            "satisfied_current": satisfied,
            "scoped_to_umo": scoped,
            "global_or_legacy": max(0, total - scoped),
            "missing_content": missing_content,
            "max_queue": int(config.get("desire_max_queue", 0) or 0),
            "timeline_events": len(timeline),
            "queue_update_events": event_counts.get("desire.queue_updated", 0),
        },
        "by_source": by_source,
        "by_kind": by_kind,
        "by_intensity": by_intensity,
        "event_counts": dict(event_counts),
        "current_desires": current_desires[:limit],
        "timeline": timeline,
    }
