"""Desire Evolution observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.desire_evolution import build_desire_evolution_snapshot  # noqa: E402
from sylanne_alpha.observability import RuntimeEventBus  # noqa: E402


def test_desire_evolution_snapshot_is_redacted_and_uses_safe_event_evidence():
    secret = "private wish about a named person"
    target_umo = "group-secret"
    target_user = "user-secret"
    bus = RuntimeEventBus(max_events=10)
    bus.emit(
        "desire.queue_updated",
        source="desire",
        payload={
            "before_count": 0,
            "after_count": 1,
            "added_content_fingerprints": ["abc123"],
            "content": secret,
            "target_umo": target_umo,
        },
        tags=["desire", "state"],
    )
    bus.emit(
        "desire.dashboard_snapshot",
        source="test",
        payload={"active": 1, "total": 1, "private_note": secret},
        tags=["desire", "dashboard"],
    )
    plugin = types.SimpleNamespace(
        _config={"desire_enabled": True, "desire_max_queue": 5},
        _runtime_event_bus=bus,
        _read_desires=lambda: [
            {
                "id": "desire-1",
                "content": secret,
                "source": "relationship",
                "kind": "outward",
                "intensity": 0.91,
                "created_at": "2026-06-08T12:00:00",
                "target_umo": target_umo,
                "target_user": target_user,
                "satisfied": False,
            }
        ],
    )

    snapshot = build_desire_evolution_snapshot(plugin, limit=10)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.desire_evolution_history.v1"
    assert snapshot["summary"]["enabled"] is True
    assert snapshot["summary"]["total_current"] == 1
    assert snapshot["summary"]["active_current"] == 1
    assert snapshot["summary"]["queue_update_events"] == 1
    assert snapshot["by_kind"]["outward"] == 1
    assert snapshot["current_desires"][0]["content_fingerprint"]
    assert snapshot["timeline"][0]["payload_keys"]
    assert snapshot["timeline"][0]["evidence"]
    assert secret not in encoded
    assert target_umo not in encoded
    assert target_user not in encoded
    assert "private_note" not in encoded
