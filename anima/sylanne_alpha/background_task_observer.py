"""Redacted background task snapshots for the Cognitive Observatory."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any


BACKGROUND_TASK_OBSERVER_SCHEMA = "anima.background_task_observer.v1"


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


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


def _task_name(task: asyncio.Task) -> str:
    try:
        return str(task.get_name() or "")[:120]
    except Exception:
        return ""


def _task_state(task: asyncio.Task) -> str:
    try:
        if task.cancelled():
            return "cancelled"
        if task.done():
            return "done"
        return "pending"
    except Exception:
        return "unknown"


def _task_exception_type(task: asyncio.Task) -> str:
    try:
        if task.cancelled() or not task.done():
            return ""
        exc = task.exception()
        return type(exc).__name__[:120] if exc is not None else ""
    except asyncio.CancelledError:
        return "CancelledError"
    except Exception as exc:
        return type(exc).__name__[:120]


def _collect_tasks(value: Any, *, source: str, rows: list[dict[str, Any]], seen: set[int]) -> None:
    if value is None:
        return
    if isinstance(value, asyncio.Task):
        ident = id(value)
        if ident in seen:
            return
        seen.add(ident)
        rows.append({
            "source": source,
            "task_id": f"task-{ident:x}"[-18:],
            "name": _task_name(value),
            "state": _task_state(value),
            "done": bool(value.done()),
            "cancelled": bool(value.cancelled()),
            "exception_type": _task_exception_type(value),
        })
        return
    if isinstance(value, dict):
        for key, item in list(value.items())[:500]:
            _collect_tasks(item, source=f"{source}:{str(key)[:60]}", rows=rows, seen=seen)
        return
    if isinstance(value, (list, set, tuple)):
        for item in list(value)[:500]:
            _collect_tasks(item, source=source, rows=rows, seen=seen)


def _managed_task_snapshot(plugin: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for attr in (
        "_background_tasks",
        "_fragment_timers",
        "_segmented_tasks",
        "_background_post_checkpoint_tasks",
        "_batch_write_task",
        "_editor_poll_task",
    ):
        _collect_tasks(getattr(plugin, attr, None), source=attr, rows=rows, seen=seen)
    by_state = Counter(row.get("state", "unknown") for row in rows)
    by_source = Counter(str(row.get("source", "unknown")).split(":", 1)[0] for row in rows)
    return {
        "summary": {
            "total": len(rows),
            "pending": by_state.get("pending", 0),
            "done": by_state.get("done", 0),
            "cancelled": by_state.get("cancelled", 0),
            "with_exception": sum(1 for row in rows if row.get("exception_type")),
            "by_state": dict(by_state),
            "by_source": dict(by_source),
        },
        "tasks": rows[:200],
    }


def _job_shape(job: Any, now: float) -> dict[str, Any]:
    lease_until = _safe_float(getattr(job, "lease_until", 0.0))
    next_retry_at = _safe_float(getattr(job, "next_retry_at", 0.0))
    return {
        "sequence": _safe_int(getattr(job, "sequence", 0)),
        "enqueued_age_seconds": round(max(0.0, now - _safe_float(getattr(job, "enqueued_at", 0.0))), 3)
        if getattr(job, "enqueued_at", 0.0)
        else 0.0,
        "attempts": _safe_int(getattr(job, "attempts", 0)),
        "next_retry_in_seconds": round(max(0.0, next_retry_at - now), 3) if next_retry_at else 0.0,
        "last_error_type": str(getattr(job, "last_error_type", "") or "")[:120],
        "dead_lettered": bool(getattr(job, "dead_lettered_at", 0.0)),
        "lease_expired": bool(lease_until and lease_until < now),
        "lease_remaining_seconds": round(max(0.0, lease_until - now), 3) if lease_until else 0.0,
    }


def _background_post_session(plugin: Any, session_key: str, now: float, *, limit: int) -> dict[str, Any]:
    queues = getattr(plugin, "_background_post_queues", {}) or {}
    active_map = getattr(plugin, "_background_post_active", {}) or {}
    dead_map = getattr(plugin, "_background_post_dead_letters", {}) or {}
    latest_map = getattr(plugin, "_background_post_latest_enqueued", {}) or {}
    committed_map = getattr(plugin, "_background_post_last_committed", {}) or {}
    worker_state = getattr(plugin, "_background_post_worker_state", {}) or {}
    checkpoint_tasks = getattr(plugin, "_background_post_checkpoint_tasks", {}) or {}
    recovered_sessions = getattr(plugin, "_background_post_recovered_sessions", set()) or set()

    queue = queues.get(session_key, []) if hasattr(queues, "get") else []
    active = active_map.get(session_key, {}) if hasattr(active_map, "get") else {}
    dead_letters = dead_map.get(session_key, []) if hasattr(dead_map, "get") else []
    latest = _safe_int(latest_map.get(session_key, 0) if hasattr(latest_map, "get") else 0)
    committed = _safe_int(committed_map.get(session_key, 0) if hasattr(committed_map, "get") else 0)
    retrying = [job for job in list(queue) if _safe_int(getattr(job, "attempts", 0)) > 0]
    expired = [
        job for job in list(active.values()) if _safe_float(getattr(job, "lease_until", 0.0)) and _safe_float(getattr(job, "lease_until", 0.0)) < now
    ] if isinstance(active, dict) else []
    warnings: list[str] = []
    if retrying:
        warnings.append("retrying")
    if dead_letters:
        warnings.append("dead_letter")
    if expired:
        warnings.append("expired_lease")
    lag = max(0, latest - committed)
    cfg = getattr(plugin, "config", {}) or {}
    warn_lag = _safe_int(cfg.get("background_post_diagnostics_warn_lag_count", 20), 20)
    if lag >= warn_lag:
        warnings.append("lag_count_high")

    checkpoint_task = checkpoint_tasks.get(session_key) if hasattr(checkpoint_tasks, "get") else None
    checkpoint_state = "none"
    if isinstance(checkpoint_task, asyncio.Task):
        checkpoint_state = _task_state(checkpoint_task)
    return {
        "session_key": session_key,
        "enabled": bool(cfg.get("background_post_assessment", True)),
        "checkpoint_enabled": bool(cfg.get("background_post_queue_checkpoint_enabled", True)),
        "recovered_from_checkpoint": session_key in recovered_sessions,
        "queue_depth": _safe_len(queue),
        "queue_maxlen": _safe_int(getattr(queue, "maxlen", 0) or 0),
        "active_workers": _safe_len(active),
        "dead_letter_count": _safe_len(dead_letters),
        "retrying_count": len(retrying),
        "expired_lease_count": len(expired),
        "latest_enqueued": latest,
        "last_committed": committed,
        "state_lag_count": lag,
        "checkpoint_task_state": checkpoint_state,
        "worker_state": {
            key: value
            for key, value in (worker_state.get(session_key, {}) if hasattr(worker_state, "get") else {}).items()
            if isinstance(value, (bool, int, float, str))
        },
        "warnings": warnings,
        "warning_level": "error" if {"dead_letter", "expired_lease"} & set(warnings) else ("warn" if warnings else "ok"),
        "queued_jobs": [_job_shape(job, now) for job in list(queue)[:limit]],
        "active_jobs": [_job_shape(job, now) for job in list(active.values())[:limit]] if isinstance(active, dict) else [],
        "dead_letters": [_job_shape(job, now) for job in list(dead_letters)[-limit:]],
    }


def _background_post_snapshot(plugin: Any, *, limit: int) -> dict[str, Any]:
    session_keys: set[str] = set()
    for attr in (
        "_background_post_queues",
        "_background_post_active",
        "_background_post_dead_letters",
        "_background_post_latest_enqueued",
        "_background_post_last_committed",
        "_background_post_worker_state",
        "_background_post_checkpoint_tasks",
    ):
        mapping = getattr(plugin, attr, None)
        if hasattr(mapping, "keys"):
            session_keys.update(str(key) for key in mapping.keys())
    now = time.time()
    sessions = [
        _background_post_session(plugin, key, now, limit=limit)
        for key in sorted(session_keys)[:200]
    ]
    return {
        "summary": {
            "sessions": len(sessions),
            "queued": sum(item["queue_depth"] for item in sessions),
            "active_workers": sum(item["active_workers"] for item in sessions),
            "dead_letters": sum(item["dead_letter_count"] for item in sessions),
            "retrying": sum(item["retrying_count"] for item in sessions),
            "expired_leases": sum(item["expired_lease_count"] for item in sessions),
            "warnings": sum(1 for item in sessions if item["warning_level"] != "ok"),
        },
        "sessions": sessions,
    }


def build_background_task_observer_snapshot(plugin: Any, *, limit: int = 20) -> dict[str, Any]:
    """Build a read-only background task and queue diagnostic snapshot."""
    limit = max(1, min(100, int(limit or 20)))
    managed = _managed_task_snapshot(plugin)
    background_post = _background_post_snapshot(plugin, limit=limit)
    return {
        "schema": BACKGROUND_TASK_OBSERVER_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "task": "task names, lifecycle state, and exception type only",
            "jobs": "reply text, context keys, identities, and event objects omitted",
            "queues": "queue depths, sequence numbers, attempts, leases, and error types only",
        },
        "summary": {
            "managed_tasks": managed["summary"]["total"],
            "pending_tasks": managed["summary"]["pending"],
            "task_exceptions": managed["summary"]["with_exception"],
            "background_post_sessions": background_post["summary"]["sessions"],
            "background_post_queued": background_post["summary"]["queued"],
            "background_post_dead_letters": background_post["summary"]["dead_letters"],
            "background_post_warnings": background_post["summary"]["warnings"],
        },
        "managed_tasks": managed,
        "background_post": background_post,
    }
