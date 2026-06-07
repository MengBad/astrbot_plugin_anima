"""State Inspector observability tests."""

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

from sylanne_alpha.state_inspector import build_state_inspector_snapshot  # noqa: E402
from sylanne_alpha.state_persistence import is_dirty, mark_dirty, swap_dirty  # noqa: E402


class FakeComputation:
    _tick_count = 3
    _last_route = "normal"


class FakeKernel:
    turns = 7
    computation = FakeComputation()


class FakeHost:
    kernel = FakeKernel()
    runtime = object()


class FakePlugin:
    def __init__(self, data_dir: Path):
        self.data_dir = str(data_dir)
        self._state_path = str(data_dir / "anima_state.json")
        self.self_notes_path = str(data_dir / "self_notes.md")
        self.desires_path = str(data_dir / "desires.json")
        self._hosts = {"session-a": FakeHost()}
        self._memory_systems = {"session-a": object()}
        self._conversation_buffers = {"session-a": ["secret user text"]}
        self._prompt_debug_snapshots = {"session-a": {"message": "do not leak"}}
        self._last_request_budgets = {"session-a": object()}
        self._background_tasks = set()

    def _sylanne_ready(self):
        return True

    def put_kv_data(self):
        pass


def test_state_inspector_snapshot_is_redacted_and_non_destructive(tmp_path):
    swap_dirty()
    plugin = FakePlugin(tmp_path)
    Path(plugin._state_path).write_text('{"x": 1}', encoding="utf-8")
    Path(plugin.self_notes_path).write_text("private self narrative", encoding="utf-8")
    Path(plugin.desires_path).write_text("[]", encoding="utf-8")
    (tmp_path / "runtime_events.jsonl").write_text("{}", encoding="utf-8")

    mark_dirty("memory", session_key="session-a")
    snapshot = build_state_inspector_snapshot(plugin)

    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert "private self narrative" not in encoded
    assert "secret user text" not in encoded
    assert snapshot["schema"] == "anima.state_inspector.v1"
    assert snapshot["summary"]["active_hosts"] == 1
    assert snapshot["summary"]["kv_api_available"] is True
    assert snapshot["sessions"][0]["session_key"] == "session-a"
    assert snapshot["sessions"][0]["dirty_subsystems"] == ["memory"]
    assert snapshot["persistence_files"]["self_notes"]["size_bytes"] > 0
    assert is_dirty("session-a") is True

    swap_dirty("session-a")
