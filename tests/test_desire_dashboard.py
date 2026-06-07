"""Desire Dashboard observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.desire_dashboard import build_desire_dashboard_snapshot  # noqa: E402


def test_desire_dashboard_snapshot_is_redacted():
    secret = "I want to ask a private question"
    plugin = types.SimpleNamespace(
        _config={"desire_enabled": True, "desire_max_queue": 5},
        _read_desires=lambda: [
            {
                "id": "desire-1",
                "content": secret,
                "source": "relationship",
                "kind": "outward",
                "intensity": 0.88,
                "created_at": "2026-06-08T12:00:00",
                "target_umo": "group-private",
                "target_user": "user-private",
                "satisfied": False,
            },
            {
                "id": "desire-2",
                "content": "internal thought",
                "source": "self",
                "intensity": 0.2,
                "satisfied": True,
            },
        ],
    )

    snapshot = build_desire_dashboard_snapshot(plugin)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.desire_dashboard.v1"
    assert snapshot["summary"]["enabled"] is True
    assert snapshot["summary"]["total"] == 2
    assert snapshot["summary"]["active"] == 1
    assert snapshot["summary"]["scoped_to_umo"] == 1
    assert snapshot["by_kind"]["outward"] == 1
    assert snapshot["by_kind"]["inward"] == 1
    assert snapshot["by_intensity"]["high"] == 1
    assert "content_fingerprint" in snapshot["active_desires"][0]
    assert secret not in encoded
    assert "group-private" not in encoded
    assert "user-private" not in encoded
