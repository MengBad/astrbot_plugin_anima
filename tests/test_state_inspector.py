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
from sylanne_alpha.state_store_audit import build_state_store_audit_snapshot  # noqa: E402
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
        self.evolution_log_path = str(data_dir / "evolution_log.jsonl")
        self.persona_core_path = str(data_dir / "persona_core.yaml")
        self.desires_path = str(data_dir / "desires.json")
        self.worldview_path = str(data_dir / "worldview.json")
        self.time_sense_path = str(data_dir / "time_sense.json")
        self.social_graph_path = str(data_dir / "social_graph.json")
        self.contradictions_path = str(data_dir / "contradictions.json")
        self.tool_learning_path = str(data_dir / "tool_learning.json")
        self.tool_diary_path = str(data_dir / "tool_diary.md")
        self.suppressed_topics_path = str(data_dir / "suppressed_topics.json")
        self.scar_dimensions_path = str(data_dir / "scar_dimensions.json")
        self.personal_capabilities_path = str(data_dir / "personal_capabilities.json")
        self.capabilities_diary_path = str(data_dir / "capabilities_diary.md")
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
    assert snapshot["state_store_audit"]["schema"] == "anima.state_store_audit.v1"
    assert snapshot["state_store_audit"]["summary"]["state_store_complete"] is False
    assert snapshot["summary"]["state_sources"] >= 4
    assert is_dirty("session-a") is True

    swap_dirty("session-a")


def test_state_store_audit_is_read_only_and_redacted(tmp_path):
    plugin = FakePlugin(tmp_path)
    Path(plugin._state_path).write_text('{"secret": "state"}', encoding="utf-8")
    Path(plugin.self_notes_path).write_text("private self narrative", encoding="utf-8")
    Path(plugin.evolution_log_path).write_text('{"event": "secret"}\n', encoding="utf-8")
    Path(plugin.desires_path).write_text('[{"content": "secret desire"}]', encoding="utf-8")
    sessions_dir = tmp_path / "sessions" / "private-session-key"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "worldview.json").write_text('{"secret": true}', encoding="utf-8")
    (sessions_dir / "time_sense.json").write_text('{"secret": true}', encoding="utf-8")

    before = sorted(path.name for path in tmp_path.rglob("*"))
    snapshot = build_state_store_audit_snapshot(plugin)
    after = sorted(path.name for path in tmp_path.rglob("*"))
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert before == after
    assert snapshot["schema"] == "anima.state_store_audit.v1"
    assert snapshot["summary"]["existing_files"] >= 4
    assert snapshot["summary"]["session_dirs"] == 1
    assert snapshot["summary"]["diff_ready_sources"] >= 4
    assert snapshot["summary"]["source_fingerprint"]
    assert snapshot["session_files"]["worldview_files"] == 1
    assert snapshot["session_files"]["time_sense_files"] == 1
    assert snapshot["capabilities"]["diff"] == "metadata_ready"
    assert snapshot["capabilities"]["audit"] == "read_only_inventory"
    assert all("metadata_fingerprint" in item for item in snapshot["files"])
    assert "private self narrative" not in encoded
    assert "secret desire" not in encoded
    assert "private-session-key" not in encoded


def test_state_store_audit_metadata_fingerprint_changes_on_file_metadata_change(tmp_path):
    plugin = FakePlugin(tmp_path)
    notes_path = Path(plugin.self_notes_path)
    notes_path.write_text("private self narrative", encoding="utf-8")

    first = build_state_store_audit_snapshot(plugin)
    notes_path.write_text("private self narrative with extra metadata length", encoding="utf-8")
    second = build_state_store_audit_snapshot(plugin)

    first_notes = next(item for item in first["files"] if item["name"] == "self_notes")
    second_notes = next(item for item in second["files"] if item["name"] == "self_notes")

    assert first_notes["metadata_fingerprint"] != second_notes["metadata_fingerprint"]
    assert first["summary"]["source_fingerprint"] != second["summary"]["source_fingerprint"]
    encoded = json.dumps(second, ensure_ascii=False)
    assert "private self narrative" not in encoded
