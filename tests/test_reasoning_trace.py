"""Reasoning Trace observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.observability import RuntimeEventBus  # noqa: E402
from sylanne_alpha.reasoning_trace import build_reasoning_trace_snapshot  # noqa: E402


def test_reasoning_trace_snapshot_is_redacted_and_explainable():
    secret_prompt = "secret prompt body should not leak"
    secret_arg = "secret tool argument should not leak"
    secret_result = "secret tool result should not leak"
    secret_response = "secret response text should not leak"

    bus = RuntimeEventBus(max_events=20)
    bus.emit(
        "prompt.injection_assembled",
        session_key="session-a",
        payload={
            "budget_chars": 3000,
            "injection_path": "sylanne_alpha",
            "injected_slots": ["self_notes", "desires"],
            "skipped_slots": ["scars"],
            "trimmed_total_chars": 10,
            "raw_total_chars": 1234,
            "prompt_text": secret_prompt,
        },
    )
    bus.emit(
        "tool.invocation_started",
        session_key="session-a",
        payload={
            "tool_name": "web_search",
            "arg_keys": ["query"],
            "arg_chars": len(secret_arg),
            "arg_values": {"query": secret_arg},
        },
    )
    bus.emit(
        "tool.invocation_finished",
        session_key="session-a",
        payload={
            "tool_name": "web_search",
            "arg_keys": ["query"],
            "arg_chars": len(secret_arg),
            "result_chars": len(secret_result),
            "success": True,
            "result_text": secret_result,
        },
    )
    bus.emit(
        "response.observed",
        session_key="session-a",
        payload={
            "text_chars": len(secret_response),
            "confidence": 0.75,
            "flags": ["stored"],
            "response_text": secret_response,
        },
    )

    plugin = types.SimpleNamespace(
        _runtime_event_bus=bus,
        _prompt_debug_snapshots={
            "session-a": {
                "timestamp": 123.45,
                "session_key": "session-a",
                "budget_chars": 3000,
                "gap_seconds": 2.5,
                "compat_mode": "merged",
                "injection_path": "sylanne_alpha",
                "injected_slots": ["self_notes"],
                "skipped_slots": [],
                "trimmed_total_chars": 0,
                "raw_total_chars": 100,
                "request_shape": {
                    "system_prompt_chars": 88,
                    "has_contexts": True,
                    "prompt_text": secret_prompt,
                },
            },
        },
        _last_request_budgets={
            "session-a": {
                "budget_chars": 3000,
                "compat_mode": "merged",
                "injected": ["self_notes"],
                "skipped": ["scars"],
            },
        },
    )

    snapshot = build_reasoning_trace_snapshot(plugin, session_key="session-a", limit=10)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.reasoning_trace.v1"
    assert snapshot["summary"]["steps"] == 4
    assert snapshot["summary"]["by_type"]["tool.invocation_started"] == 1
    assert snapshot["summary"]["by_type"]["tool.invocation_finished"] == 1
    decisions = [step["decision"] for step in snapshot["steps"]]
    assert decisions.count("assemble_prompt_injection") == 1
    assert decisions.count("llm_tool_use") == 2
    assert decisions.count("observe_response") == 1
    assert snapshot["prompt_debug"][0]["request_shape"] == {
        "system_prompt_chars": 88,
        "has_contexts": True,
    }
    assert secret_prompt not in encoded
    assert secret_arg not in encoded
    assert secret_result not in encoded
    assert secret_response not in encoded


def test_reasoning_trace_respects_session_filter():
    bus = RuntimeEventBus(max_events=10)
    bus.emit("response.observed", session_key="session-a", payload={"text_chars": 10})
    bus.emit("response.observed", session_key="session-b", payload={"text_chars": 20})
    plugin = types.SimpleNamespace(
        _runtime_event_bus=bus,
        _prompt_debug_snapshots={},
        _last_request_budgets={},
    )

    snapshot = build_reasoning_trace_snapshot(plugin, session_key="session-b")

    assert snapshot["summary"]["steps"] == 1
    assert snapshot["steps"][0]["session_key"] == "session-b"
    assert snapshot["steps"][0]["evidence"]["text_chars"] == 20
