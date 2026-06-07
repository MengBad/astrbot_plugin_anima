"""Redacted Desire Dashboard snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any


DESIRE_DASHBOARD_SCHEMA = "anima.desire_dashboard.v1"


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


def _desire_payload(desire: dict[str, Any], now: float) -> dict[str, Any]:
    content = str(desire.get("content", "") or "")
    created_at = _parse_ts(desire.get("created_at"))
    age_seconds = round(max(0.0, now - created_at), 3) if created_at else 0.0
    target_umo = str(desire.get("target_umo", "") or "")
    target_user = str(desire.get("target_user", "") or "")
    intensity = _float(desire.get("intensity", 0.0))
    return {
        "id": str(desire.get("id", "") or "")[:24],
        "content_chars": len(content),
        "content_fingerprint": _fingerprint(content),
        "source": str(desire.get("source", "") or ""),
        "kind": _desire_kind(desire),
        "intensity": intensity,
        "intensity_bucket": _bucket_intensity(intensity),
        "satisfied": bool(desire.get("satisfied", False)),
        "created_at_ts": created_at,
        "age_seconds": age_seconds,
        "target_umo_hash": _fingerprint(target_umo),
        "target_user_hash": _fingerprint(target_user),
        "has_target_umo": bool(target_umo),
        "has_target_user": bool(target_user),
        "repeat_count": int(desire.get("repeat_count", 0) or 0),
        "max_repeats": int(desire.get("max_repeats", 0) or 0),
    }


def _inc(mapping: dict[str, int], key: str) -> None:
    mapping[key] = mapping.get(key, 0) + 1


def build_desire_dashboard_snapshot(plugin: Any, *, limit: int = 20) -> dict[str, Any]:
    """Build a redacted desire queue snapshot.

    This reads the queue through the plugin's existing read path and never writes
    or mutates desires. Desire content is represented only by length and hash.
    """
    limit = max(1, min(100, int(limit or 20)))
    try:
        desires = plugin._read_desires() if hasattr(plugin, "_read_desires") else []
    except Exception:
        desires = []
    if not isinstance(desires, list):
        desires = []

    now = time.time()
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_bucket: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    scoped = 0
    satisfied = 0
    missing_content = 0
    active_payloads: list[dict[str, Any]] = []

    for raw in desires:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source", "") or "unknown")
        kind = _desire_kind(raw)
        intensity = _float(raw.get("intensity", 0.0))
        bucket = _bucket_intensity(intensity)
        _inc(by_source, source)
        _inc(by_kind, kind)
        _inc(by_bucket, bucket)
        if raw.get("target_umo"):
            scoped += 1
        if raw.get("satisfied"):
            satisfied += 1
        if not str(raw.get("content", "") or "").strip():
            missing_content += 1
        if not raw.get("satisfied"):
            active_payloads.append(_desire_payload(raw, now))

    active_payloads.sort(key=lambda item: item.get("intensity", 0.0), reverse=True)
    config = getattr(plugin, "_config", None) or getattr(plugin, "config", {}) or {}
    max_queue = int(config.get("desire_max_queue", 0) or 0)
    return {
        "schema": DESIRE_DASHBOARD_SCHEMA,
        "timestamp": now,
        "redaction": {
            "content": "omitted; content_chars and sha256 fingerprints only",
            "targets": "UMO and user identifiers omitted; sha256 fingerprints only",
        },
        "summary": {
            "enabled": bool(config.get("desire_enabled", False)),
            "total": len([d for d in desires if isinstance(d, dict)]),
            "active": len(active_payloads),
            "satisfied": satisfied,
            "scoped_to_umo": scoped,
            "global_or_legacy": max(0, len([d for d in desires if isinstance(d, dict)]) - scoped),
            "missing_content": missing_content,
            "max_queue": max_queue,
            "queue_fill_ratio": round((len(desires) / max_queue), 4) if max_queue > 0 else 0.0,
        },
        "by_source": by_source,
        "by_kind": by_kind,
        "by_intensity": by_bucket,
        "active_desires": active_payloads[:limit],
    }
