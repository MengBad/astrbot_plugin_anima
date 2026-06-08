"""Session Replay observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.memory_system import ConversationBuffer  # noqa: E402
from sylanne_alpha.observability import RuntimeEventBus  # noqa: E402
from sylanne_alpha.session_replay import build_session_replay_snapshot  # noqa: E402


def test_session_replay_snapshot_is_redacted_and_replayable():
    secret_user = "private user text should not leak"
    secret_bot = "private bot text should not leak"
    secret_tool_arg = "private tool arg should not leak"
    secret_tool_result = "private tool result should not leak"

    buf = ConversationBuffer(session_key="session-a")
    buf.append("user", secret_user, ts=10.0)
    buf.append("bot", secret_bot, ts=11.0)

    bus = RuntimeEventBus(max_events=20)
    bus.emit(
        "prompt.injection_assembled",
        session_key="session-a",
        ts=9.0,
        payload={
            "budget_chars": 2000,
            "injection_path": "sylanne_alpha",
            "injected_slots": ["self_notes"],
            "prompt_text": secret_user,
        },
    )
    bus.emit(
        "tool.invocation_finished",
        session_key="session-a",
        ts=10.5,
        payload={
            "tool_name": "lookup",
            "arg_keys": ["query"],
            "arg_chars": len(secret_tool_arg),
            "result_chars": len(secret_tool_result),
            "success": True,
            "arg_values": {"query": secret_tool_arg},
            "result_text": secret_tool_result,
        },
    )
    bus.emit(
        "response.observed",
        session_key="session-a",
        ts=11.5,
        payload={"text_chars": len(secret_bot), "flags": ["safe"], "response_text": secret_bot},
    )

    plugin = types.SimpleNamespace(
        _runtime_event_bus=bus,
        _conversation_buffers={"session-a": buf},
        _hosts={},
        _memory_systems={},
        _prompt_debug_snapshots={},
        _last_request_budgets={},
    )

    snapshot = build_session_replay_snapshot(plugin, session_key="session-a", limit=20)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.session_replay.v1"
    assert snapshot["summary"]["sessions"] == 1
    assert snapshot["summary"]["runtime_events"] == 3
    assert snapshot["summary"]["buffer_messages"] == 2
    timeline = snapshot["sessions"][0]["timeline"]
    assert any(item["kind"] == "buffer_message" and item["role"] == "user" for item in timeline)
    assert any(item["kind"] == "runtime_event" and item["action"] == "tool_finished" for item in timeline)
    assert "text_fingerprint" in next(item for item in timeline if item.get("role") == "user")
    assert secret_user not in encoded
    assert secret_bot not in encoded
    assert secret_tool_arg not in encoded
    assert secret_tool_result not in encoded


def test_session_replay_respects_session_filter():
    buf_a = ConversationBuffer(session_key="session-a")
    buf_b = ConversationBuffer(session_key="session-b")
    buf_a.append("user", "a-only", ts=1.0)
    buf_b.append("user", "b-only", ts=2.0)
    bus = RuntimeEventBus(max_events=10)
    bus.emit("response.observed", session_key="session-a", ts=1.5, payload={"text_chars": 1})
    bus.emit("response.observed", session_key="session-b", ts=2.5, payload={"text_chars": 2})
    plugin = types.SimpleNamespace(
        _runtime_event_bus=bus,
        _conversation_buffers={"session-a": buf_a, "session-b": buf_b},
        _hosts={},
        _memory_systems={},
        _prompt_debug_snapshots={},
        _last_request_budgets={},
    )

    snapshot = build_session_replay_snapshot(plugin, session_key="session-b")

    assert len(snapshot["sessions"]) == 1
    assert snapshot["sessions"][0]["session_key"] == "session-b"
    assert snapshot["summary"]["buffer_messages"] == 1
    assert "a-only" not in json.dumps(snapshot, ensure_ascii=False)
