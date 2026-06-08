"""Memory Recall Replay observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.memory_recall_replay import build_memory_recall_replay_snapshot  # noqa: E402
from sylanne_alpha.memory_system import MemoryItem, MemorySystem  # noqa: E402
from sylanne_alpha.observability import RuntimeEventBus  # noqa: E402


def test_memory_recall_replay_snapshot_is_redacted_and_read_only():
    secret_memory = "private recalled memory body should not leak"
    secret_query = "private user query should not leak"
    secret_prompt = "private prompt body should not leak"
    memory = MemorySystem()
    item = MemoryItem(
        id="memory-secret",
        text=secret_memory,
        weight=0.8,
        temperature=0.2,
        age_ticks=5,
        created_at=123.0,
        recall_count=2,
        last_recalled_tick=7,
        embedding=[0.1, 0.2],
    )
    memory._l2.append(item)
    memory._recalled_l2_items = [item]
    before_weight = item.weight
    before_recall_count = item.recall_count

    bus = RuntimeEventBus(max_events=10)
    bus.emit(
        "memory.recall_performed",
        session_key="session-a",
        payload={
            "query_chars": len(secret_query),
            "query_fingerprint": "abc123",
            "query_text": secret_query,
            "result_count": 1,
            "l2_recalled_count": 1,
            "layer_counts": {"L2": 1},
            "reason_counts": {"keyword_match": 1},
        },
    )
    bus.emit(
        "prompt.injection_assembled",
        session_key="session-a",
        payload={
            "budget_chars": 2000,
            "injection_path": "nosave_context",
            "injected_slots": ["memory"],
            "prompt_text": secret_prompt,
        },
    )
    plugin = types.SimpleNamespace(
        _memory_systems={"session-a": memory},
        _runtime_event_bus=bus,
        _prompt_debug_snapshots={
            "session-a": {
                "timestamp": 99.0,
                "session_key": "session-a",
                "budget_chars": 2000,
                "gap_seconds": 3600,
                "injection_path": "nosave_context",
                "raw_lengths": {"memory": len(secret_memory), "state": 10},
                "trimmed_lengths": {"memory": 40},
                "injected_slots": ["memory"],
                "skipped_slots": [],
                "prompt_text": secret_prompt,
            }
        },
    )

    snapshot = build_memory_recall_replay_snapshot(plugin, session_key="session-a", limit=10)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.memory_recall_replay.v1"
    assert snapshot["summary"]["sessions"] == 1
    assert snapshot["summary"]["recalled_l2"] == 1
    assert snapshot["summary"]["memory_injections"] == 1
    assert snapshot["sessions"][0]["memory"]["last_recalled_l2"][0]["text_fingerprint"]
    assert snapshot["sessions"][0]["events"][0]["evidence"]
    assert item.weight == before_weight
    assert item.recall_count == before_recall_count
    assert secret_memory not in encoded
    assert secret_query not in encoded
    assert secret_prompt not in encoded
