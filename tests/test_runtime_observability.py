"""Runtime observability foundation tests."""

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

from sylanne_alpha.observability import RuntimeEventBus  # noqa: E402
from sylanne_alpha.llm_response_pipeline import LLMResponsePipeline  # noqa: E402
from sylanne_alpha.llm_request_pipeline import _record_prompt_debug_snapshot  # noqa: E402


def test_runtime_event_bus_records_filters_and_sanitizes_payload():
    bus = RuntimeEventBus(max_events=3)
    bus.emit("state.write", session_key="a", payload={"text": "x" * 1200})
    bus.emit("response.observed", session_key="b", severity="debug")
    bus.emit("desire.queue_updated", session_key="a")
    bus.emit("plugin.terminated", session_key="a")

    recent = bus.recent(limit=10)
    assert [event["type"] for event in recent] == [
        "plugin.terminated",
        "desire.queue_updated",
        "response.observed",
    ]
    assert bus.recent(limit=10, session_key="b")[0]["type"] == "response.observed"
    assert bus.stats()["total"] == 3

    sanitized = RuntimeEventBus().emit("payload", payload={"text": "x" * 1200})
    assert len(sanitized["payload"]["text"]) == 1000


def test_runtime_event_bus_persists_and_reloads_timeline(tmp_path):
    timeline = tmp_path / "runtime_events.jsonl"
    bus = RuntimeEventBus(max_events=5, timeline_path=timeline)
    first = bus.emit("state.atomic_update_committed", session_key="s1")
    second = bus.emit("response.observed", session_key="s1")

    lines = timeline.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "state.atomic_update_committed"

    with open(timeline, "a", encoding="utf-8") as f:
        f.write("{bad-json\n")

    reloaded = RuntimeEventBus(max_events=5, timeline_path=timeline)
    recent = reloaded.recent(limit=5)
    assert [event["type"] for event in recent[:2]] == [
        "response.observed",
        "state.atomic_update_committed",
    ]
    next_event = reloaded.emit("desire.queue_updated", session_key="s1")
    assert next_event["id"] == max(first["id"], second["id"]) + 1


class ResponsePlugin:
    def __init__(self):
        self._config = {
            "sylanne_alpha_realtime_chat_enabled": False,
            "sylanne_alpha_realtime_intercept_llm_response": False,
        }
        self._background_tasks = set()
        self._conversation_buffers = {}
        self._last_bot_texts = {}
        self._runtime_event_bus = RuntimeEventBus()
        self.observed = []

    def _session_key(self, event):
        return "session-a"

    def _schedule_buffer_persist(self, session_key):
        pass

    def _has_conversation_manager(self):
        return False

    def _emit_runtime_event(self, event_type, **kwargs):
        return self._runtime_event_bus.emit(event_type, **kwargs)

    async def observe_response(self, session_key, **kwargs):
        self.observed.append((session_key, kwargs))
        return {"ok": True}


def test_response_observation_emits_runtime_event():
    async def run():
        plugin = ResponsePlugin()
        pipeline = LLMResponsePipeline(plugin)
        event = types.SimpleNamespace(unified_msg_origin="group:1", platform_meta=None)
        response = types.SimpleNamespace(completion_text="hello")

        await pipeline._on_llm_response_inner(event, response)
        await asyncio.gather(*list(plugin._background_tasks))

        events = plugin._runtime_event_bus.recent(limit=10)
        assert any(event["type"] == "response.observed" for event in events)

    asyncio.run(run())


def test_prompt_debug_snapshot_is_redacted_and_emits_event():
    class Plugin:
        def __init__(self):
            self._prompt_debug_snapshots = {}
            self._runtime_event_bus = RuntimeEventBus()

        def _emit_runtime_event(self, event_type, **kwargs):
            return self._runtime_event_bus.emit(event_type, **kwargs)

    plugin = Plugin()
    request = types.SimpleNamespace(system_prompt="sys", prompt="user", contexts=[])
    budget = types.SimpleNamespace(compat_mode="", injected=[], skipped=[])
    secret_memory = "private memory that must not be stored"

    _record_prompt_debug_snapshot(
        plugin,
        session_key="session-a",
        request=request,
        budget=budget,
        gap_seconds=12.34,
        total_budget=1200,
        raw_fragments={"memory": secret_memory, "state": "warm"},
        trimmed_fragments={"state": "warm"},
        current_prompt="current prompt text",
        message_text="hello",
    )

    snapshot = plugin._prompt_debug_snapshots["session-a"]
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert secret_memory not in encoded
    assert snapshot["raw_lengths"]["memory"] == len(secret_memory)
    assert snapshot["trimmed_lengths"] == {"state": 4}
    assert snapshot["skipped_slots"] == ["memory"]
    assert snapshot["request_shape"]["system_prompt_chars"] == 3

    events = plugin._runtime_event_bus.recent(limit=5)
    assert events[0]["type"] == "prompt.injection_assembled"
    assert events[0]["payload"]["injected_slots"] == ["state"]


def test_event_snapshot_and_rollback():
    bus = RuntimeEventBus(max_events=100)
    bus.emit("event.a", session_key="s1")
    bus.emit("event.b", session_key="s1")
    bus.emit("event.c", session_key="s1")

    snapshot = bus.snapshot("before")
    assert snapshot.name == "before"
    assert len(snapshot.events) == 3

    bus.emit("event.d", session_key="s1")
    bus.emit("event.e", session_key="s1")
    assert len(bus.recent(limit=10)) == 5

    new_snapshot = bus.snapshot("after")
    diff = bus.diff(snapshot, new_snapshot)
    assert diff.has_changes
    assert len(diff.added) == 2
    assert len(diff.removed) == 0

    bus.rollback(snapshot)
    assert len(bus.recent(limit=10)) == 3
    assert bus.recent(limit=10)[0]["type"] == "event.c"


def test_event_compact():
    bus = RuntimeEventBus(max_events=100)
    import time
    old_ts = time.time() - (8 * 86400)
    bus.emit("old.event", ts=old_ts)
    bus.emit("new.event")
    bus.emit("new.event.2")

    removed = bus.compact(keep_days=7)
    assert removed == 1
    assert len(bus.recent(limit=10)) == 2


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
