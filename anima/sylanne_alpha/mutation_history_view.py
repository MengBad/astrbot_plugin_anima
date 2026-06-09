"""Redacted mutation-history projection for WebUI observability."""

from __future__ import annotations

import hashlib
from typing import Any


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _bounded_limit(limit: Any, default: int = 50, maximum: int = 100) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = default
    return max(1, min(maximum, n))


def _safe_str(value: Any, *, default: str = "", maximum: int = 80) -> str:
    text = str(value if value is not None else default)
    return text[:maximum]


def build_redacted_mutation_history(
    state: dict[str, Any] | None,
    *,
    limit: Any = 50,
) -> dict[str, Any]:
    """Return mutation-history metadata without exposing mutation descriptions.

    ``mutation_history`` descriptions can contain LLM-generated persona-core
    fragments. The Observatory only needs provenance and stable evidence, so
    expose length/fingerprint instead of raw text.
    """
    raw_history = []
    if isinstance(state, dict):
        raw_history = state.get("mutation_history", []) or []
    if not isinstance(raw_history, list):
        raw_history = []

    bounded = _bounded_limit(limit)
    selected = raw_history[-bounded:]
    history: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "")
        history.append(
            {
                "timestamp": _safe_str(item.get("timestamp"), maximum=40),
                "type": _safe_str(item.get("type"), default="mutation", maximum=64)
                or "mutation",
                "triggered_by": _safe_str(item.get("triggered_by"), maximum=64),
                "description_redacted": True,
                "description_length": len(description),
                "description_fingerprint": _fingerprint(description)
                if description
                else "",
            }
        )
    return {
        "schema_version": "anima.mutation_history.v1",
        "ok": True,
        "history": history,
        "count": len(history),
        "total_count": len(raw_history),
        "limit": bounded,
    }
