"""Phase 2 stability regressions for persistence, budgets, and response observation."""

import asyncio
import json
import os
import sys
import tempfile
import threading
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
        ),
        "AstrBotConfig": dict,
    },
)
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})

from anima.mixins.state_io import StateIOMixin  # noqa: E402
from anima.mixins.desire import DesireMixin  # noqa: E402
from sylanne_alpha.llm_request_pipeline import _compute_injection_budget  # noqa: E402
from sylanne_alpha.llm_response_pipeline import LLMResponsePipeline  # noqa: E402


class StateHost(StateIOMixin):
    def __init__(self, data_dir):
        self._io_lock = threading.Lock()
        self._state_path = os.path.join(data_dir, "anima_state.json")


class DesireHost(StateIOMixin, DesireMixin):
    def __init__(self, data_dir):
        self._io_lock = threading.Lock()
        self.config = {}
        self.desires_path = os.path.join(data_dir, "desires.json")


class ResponsePlugin:
    def __init__(self):
        self._config = {
            "sylanne_alpha_realtime_chat_enabled": False,
            "sylanne_alpha_realtime_intercept_llm_response": False,
        }
        self._background_tasks = set()
        self._conversation_buffers = {}
        self._last_bot_texts = {}
        self.observed = []

    def _session_key(self, event):
        return "session-a"

    def _schedule_buffer_persist(self, session_key):
        self.persisted = session_key

    def _has_conversation_manager(self):
        return False

    async def observe_response(self, session_key, **kwargs):
        self.observed.append((session_key, kwargs))
        return {"ok": True}


def test_corrupt_state_is_backed_up_and_not_replaced_with_empty_state():
    with tempfile.TemporaryDirectory(prefix="anima_phase2_state_") as tmp:
        host = StateHost(tmp)
        with open(host._state_path, "w", encoding="utf-8") as f:
            f.write("{not-json")

        host._atomic_update_state(lambda state: state.update({"x": 1}))

        assert not os.path.exists(host._state_path)
        backups = list(Path(tmp).glob("anima_state.json.corrupt-json.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{not-json"


def test_atomic_update_state_writes_valid_state_atomically():
    with tempfile.TemporaryDirectory(prefix="anima_phase2_state_") as tmp:
        host = StateHost(tmp)
        host._atomic_update_state(lambda state: state.update({"x": 1}))

        with open(host._state_path, encoding="utf-8") as f:
            assert json.load(f) == {"x": 1}


def test_atomic_update_desires_rechecks_latest_file_contents():
    with tempfile.TemporaryDirectory(prefix="anima_phase2_desire_") as tmp:
        host = DesireHost(tmp)
        host._write_desires([{"content": "old", "intensity": 0.5}])

        def update(desires):
            desires.append({"content": "new", "intensity": 0.6})
            return desires

        host._atomic_update_desires(update)

        assert [d["content"] for d in host._read_desires()] == ["old", "new"]


def test_invalid_injection_budget_config_falls_back_to_dynamic_budget():
    assert _compute_injection_budget(1000, {"state_injection_max_added_chars": "bad"}) == 2400
    assert _compute_injection_budget(1000, {"state_injection_max_added_chars": -10}) == 0
    assert _compute_injection_budget(1000, {"state_injection_max_added_chars": 999999}) == 20000


def test_response_is_observed_when_realtime_intercept_is_disabled():
    async def run():
        plugin = ResponsePlugin()
        pipeline = LLMResponsePipeline(plugin)
        event = types.SimpleNamespace(unified_msg_origin="group:1", platform_meta=None)
        response = types.SimpleNamespace(completion_text="hello [sylanne_fake] world")

        await pipeline._on_llm_response_inner(event, response)
        await asyncio.gather(*list(plugin._background_tasks))

        assert response.completion_text == "hello  world"
        assert plugin.observed
        assert plugin.observed[0][0] == "session-a"
        assert plugin.observed[0][1]["text"] == "hello  world"

    asyncio.run(run())


def test_cron_response_is_not_observed_when_realtime_intercept_is_disabled():
    async def run():
        plugin = ResponsePlugin()
        pipeline = LLMResponsePipeline(plugin)
        event = types.SimpleNamespace(unified_msg_origin="cron:rumination", platform_meta=None)
        response = types.SimpleNamespace(completion_text="internal summary")

        await pipeline._on_llm_response_inner(event, response)
        assert not plugin._background_tasks
        assert not plugin.observed

    asyncio.run(run())
