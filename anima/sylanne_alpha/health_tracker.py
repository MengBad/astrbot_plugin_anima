import time
from collections import deque
from typing import Dict, Any

class SubsystemHealthTracker:
    """Tracks subsystem health diagnostics using a 5-minute sliding window."""
    
    def __init__(self) -> None:
        self._errors: Dict[str, deque] = {
            "core": deque(),
            "models": deque(),
            "memory": deque(),
            "autonomy": deque(),
            "safety": deque(),
        }
        self._warnings: Dict[str, deque] = {
            "core": deque(),
            "models": deque(),
            "memory": deque(),
            "autonomy": deque(),
            "safety": deque(),
        }
        self._last_active: Dict[str, float] = {
            "core": time.time(),
            "models": time.time(),
            "memory": time.time(),
            "autonomy": time.time(),
            "safety": time.time(),
        }

    def record_active(self, subsystem: str) -> None:
        if subsystem in self._last_active:
            self._last_active[subsystem] = time.time()

    def record_error(self, subsystem: str) -> None:
        if subsystem in self._errors:
            self._errors[subsystem].append(time.time())
            self._last_active[subsystem] = time.time()

    def record_warning(self, subsystem: str) -> None:
        if subsystem in self._warnings:
            self._warnings[subsystem].append(time.time())
            self._last_active[subsystem] = time.time()

    def get_error_count_5m(self, subsystem: str) -> int:
        if subsystem not in self._errors:
            return 0
        now = time.time()
        cutoff = now - 300.0
        q = self._errors[subsystem]
        while q and q[0] < cutoff:
            q.popleft()
        return len(q)

    def get_warning_count_5m(self, subsystem: str) -> int:
        if subsystem not in self._warnings:
            return 0
        now = time.time()
        cutoff = now - 300.0
        q = self._warnings[subsystem]
        while q and q[0] < cutoff:
            q.popleft()
        return len(q)

    def get_status(self, subsystem: str) -> str:
        errs = self.get_error_count_5m(subsystem)
        warns = self.get_warning_count_5m(subsystem)
        if errs > 3:
            return "red"
        elif errs > 0 or warns > 0:
            return "yellow"
        return "green"

    def get_last_active(self, subsystem: str) -> float:
        return self._last_active.get(subsystem, 0.0)

# Global tracker instance
global_health_tracker = SubsystemHealthTracker()
