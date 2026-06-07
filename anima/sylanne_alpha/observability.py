"""Runtime observability primitives for the Cognitive Observatory.

The event bus is intentionally lightweight: it records structured runtime
events for debugging and WebUI inspection, but it must never influence the
cognitive decision path. All producers should treat emit failures as
non-fatal.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable

try:
    from astrbot.api import logger  # type: ignore
except ImportError:
    import logging as _logging

    logger = _logging.getLogger("astrbot_plugin_anima")  # type: ignore


class RuntimeEventBus:
    """In-memory ring buffer for structured cognitive runtime events."""

    def __init__(self, max_events: int = 2000, timeline_path: str | os.PathLike[str] | None = None) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_events)))
        self._timeline_path = Path(timeline_path) if timeline_path else None
        self._write_lock = threading.Lock()
        max_loaded_id = self._load_recent_timeline()
        self._sequence = itertools.count(max_loaded_id + 1)
        self._subscribers: list[Any] = []

    def emit(
        self,
        event_type: str,
        *,
        session_key: str = "",
        severity: str = "info",
        source: str = "",
        payload: dict[str, Any] | None = None,
        tags: Iterable[str] | None = None,
        ts: float | None = None,
    ) -> dict[str, Any]:
        """Append one structured event and notify best-effort subscribers."""
        event = {
            "schema_version": "anima.runtime_event.v1",
            "id": next(self._sequence),
            "ts": float(ts if ts is not None else time.time()),
            "type": str(event_type or "unknown")[:120],
            "session_key": str(session_key or "")[:240],
            "severity": str(severity or "info")[:40],
            "source": str(source or "")[:120],
            "payload": self._sanitize_payload(payload or {}),
            "tags": [str(tag)[:80] for tag in list(tags or [])[:12]],
        }
        self._events.append(event)
        self._append_timeline(event)
        for callback in list(self._subscribers):
            try:
                callback(dict(event))
            except Exception as exc:
                logger.debug(f"Sylanne observability subscriber failed: {exc}")
        return event

    def subscribe(self, callback: Any) -> None:
        """Register a best-effort synchronous subscriber."""
        if callable(callback) and callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Any) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def recent(
        self,
        limit: int = 100,
        *,
        session_key: str = "",
        event_type: str = "",
        severity: str = "",
    ) -> list[dict[str, Any]]:
        """Return recent events, newest first."""
        try:
            limit = max(0, min(1000, int(limit)))
        except (TypeError, ValueError):
            limit = 100
        rows = list(self._events)
        if session_key:
            rows = [event for event in rows if event.get("session_key") == session_key]
        if event_type:
            rows = [event for event in rows if event.get("type") == event_type]
        if severity:
            rows = [event for event in rows if event.get("severity") == severity]
        return [dict(event) for event in reversed(rows[-limit:])]

    def stats(self) -> dict[str, Any]:
        """Return counters for quick WebUI health summaries."""
        events = list(self._events)
        by_type = Counter(str(event.get("type") or "unknown") for event in events)
        by_severity = Counter(str(event.get("severity") or "info") for event in events)
        return {
            "total": len(events),
            "by_type": dict(by_type.most_common(20)),
            "by_severity": dict(by_severity),
            "last_event_id": events[-1]["id"] if events else 0,
            "persistent": self._timeline_path is not None,
        }

    def _load_recent_timeline(self) -> int:
        """Load the newest persisted events into the memory ring buffer."""
        if self._timeline_path is None or not self._timeline_path.exists():
            return 0
        max_id = 0
        try:
            with open(self._timeline_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as exc:
            logger.debug(f"Sylanne runtime timeline load failed: {exc}")
            return 0
        for line in lines[-self._events.maxlen :]:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event = self._normalize_loaded_event(event)
            self._events.append(event)
            try:
                max_id = max(max_id, int(event.get("id") or 0))
            except (TypeError, ValueError):
                pass
        return max_id

    def _append_timeline(self, event: dict[str, Any]) -> None:
        """Best-effort append to the persistent timeline JSONL file."""
        if self._timeline_path is None:
            return
        try:
            parent = self._timeline_path.parent
            if parent:
                parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
            with self._write_lock:
                with open(self._timeline_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as exc:
            logger.debug(f"Sylanne runtime timeline append failed: {exc}")

    def _normalize_loaded_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalize old or externally edited timeline rows before replaying them."""
        return {
            "schema_version": str(event.get("schema_version") or "anima.runtime_event.v1")[:80],
            "id": event.get("id", 0),
            "ts": float(event.get("ts") or 0.0),
            "type": str(event.get("type") or "unknown")[:120],
            "session_key": str(event.get("session_key") or "")[:240],
            "severity": str(event.get("severity") or "info")[:40],
            "source": str(event.get("source") or "")[:120],
            "payload": self._sanitize_payload(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
            "tags": [str(tag)[:80] for tag in list(event.get("tags") or [])[:12]],
        }

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in list(payload.items())[:50]:
            clean[str(key)[:80]] = self._sanitize_value(value)
        return clean

    def _sanitize_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:1000]
        if isinstance(value, dict):
            return {
                str(k)[:80]: self._sanitize_value(v)
                for k, v in list(value.items())[:25]
            }
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_value(item) for item in list(value)[:25]]
        return str(value)[:500]
