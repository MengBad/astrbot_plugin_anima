"""Cognitive Observatory 深化测试。"""

import asyncio
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


def _stub(name, attrs=None):
    module = types.ModuleType(name)
    module.__path__ = []
    for key, value in (attrs or {}).items():
        setattr(module, key, value)
    sys.modules[name] = module


_stub("astrbot")
_stub(
    "astrbot.api",
    {
        "logger": types.SimpleNamespace(
            **{name: (lambda *a, **kw: None) for name in ["debug", "info", "warning", "error"]}
        )
    },
)

from sylanne_alpha.observability import RuntimeEventBus, EventSnapshot, EventDiff  # noqa: E402


def test_event_snapshot_and_diff():
    bus = RuntimeEventBus(max_events=100)
    bus.emit("event.a", session_key="s1")
    bus.emit("event.b", session_key="s1")
    bus.emit("event.c", session_key="s1")

    snap1 = bus.snapshot("before")
    assert snap1.name == "before"
    assert len(snap1.events) == 3

    bus.emit("event.d", session_key="s1")
    bus.emit("event.e", session_key="s1")

    snap2 = bus.snapshot("after")
    diff = bus.diff(snap1, snap2)

    assert diff.has_changes
    assert len(diff.added) == 2
    assert len(diff.removed) == 0


def test_event_rollback():
    bus = RuntimeEventBus(max_events=100)
    bus.emit("event.a", session_key="s1")
    bus.emit("event.b", session_key="s1")

    snap = bus.snapshot("rollback_target")

    bus.emit("event.c", session_key="s1")
    bus.emit("event.d", session_key="s1")
    assert len(bus.recent(limit=10)) == 4

    bus.rollback(snap)
    assert len(bus.recent(limit=10)) == 2


def test_event_compact():
    import time
    bus = RuntimeEventBus(max_events=100)

    old_ts = time.time() - (8 * 86400)
    bus.emit("old.event", ts=old_ts)
    bus.emit("new.event")

    removed = bus.compact(keep_days=7)
    assert removed == 1
    assert len(bus.recent(limit=10)) == 1


def test_event_snapshot_management():
    bus = RuntimeEventBus(max_events=100)
    bus.emit("event.a")

    snap1 = bus.snapshot("snap1")
    snap2 = bus.snapshot("snap2")

    assert bus.list_snapshots() == ["snap1", "snap2"]
    assert bus.get_snapshot("snap1") is snap1

    assert bus.delete_snapshot("snap1") is True
    assert bus.get_snapshot("snap1") is None
    assert bus.delete_snapshot("snap1") is False


def test_event_search():
    bus = RuntimeEventBus(max_events=100)
    bus.emit("state.write", session_key="s1", payload={"key": "value"})
    bus.emit("response.observed", session_key="s2")
    bus.emit("desire.queue_updated", session_key="s1")

    all_events = bus.recent(limit=100)
    assert len(all_events) == 3

    s1_events = bus.recent(limit=100, session_key="s1")
    assert len(s1_events) == 2

    state_events = bus.recent(limit=100, event_type="state.write")
    assert len(state_events) == 1


def test_cross_session_trend():
    class MockHost:
        def __init__(self):
            self.kernel = types.SimpleNamespace(
                turns=10,
                _personality=lambda: {"traits": {"warmth": 0.7, "arousal": 0.3}},
                computation=types.SimpleNamespace(
                    engine=types.SimpleNamespace(
                        observe=lambda: {"warmth": 0.7, "arousal": 0.3, "valence": 0.5},
                        _coherence=0.8,
                        diagnostics=lambda: {"void": {}},
                    ),
                    boundary=types.SimpleNamespace(
                        to_dict=lambda: {"integrity": 0.9, "stability": 0.85}
                    ),
                ),
            )

    hosts = {"session-1": MockHost(), "session-2": MockHost()}

    trends = []
    for session_key, host in hosts.items():
        kernel = host.kernel
        comp = kernel.computation
        emotion = comp.engine.observe()
        boundary = comp.boundary.to_dict()
        personality = kernel._personality()

        trends.append({
            "session_key": session_key,
            "turns": kernel.turns,
            "emotion": {
                "warmth": round(float(emotion.get("warmth", 0)), 3),
                "arousal": round(float(emotion.get("arousal", 0)), 3),
            },
            "boundary": {
                "integrity": round(float(boundary.get("integrity", 1.0)), 3),
            },
            "personality_traits": {
                k: round(float(v), 3)
                for k, v in (personality.get("traits") or {}).items()
                if isinstance(v, (int, float))
            },
        })

    assert len(trends) == 2
    assert trends[0]["session_key"] == "session-1"
    assert trends[0]["turns"] == 10
    assert trends[0]["emotion"]["warmth"] == 0.7
    assert trends[0]["boundary"]["integrity"] == 0.9
    assert trends[0]["personality_traits"]["warmth"] == 0.7
