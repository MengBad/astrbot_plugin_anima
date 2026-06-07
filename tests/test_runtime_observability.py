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
