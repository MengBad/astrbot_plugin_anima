"""Scar Explorer observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.scar_algebra import Scar, ScarredState, HealingStage  # noqa: E402
from sylanne_alpha.scar_explorer import build_scar_explorer_snapshot  # noqa: E402


def test_scar_explorer_snapshot_reports_sylanne_and_legacy_sources_without_raw_text():
    scar_state = ScarredState()
    scar_state.scars.append(Scar(dimension=3, timestamp=123.0, stage=HealingStage.RAW))
    scar_state.scars.append(Scar(dimension=6, timestamp=124.0, stage=HealingStage.SCARRED))
    scar_state._session_scar_count = 2
    scar_state._session_scar_cap = 3
    scar_state._circuit_breaker_active = True
    scar_state._circuit_breaker_remaining = 9

    engine = types.SimpleNamespace(scar_state=scar_state)
    computation = types.SimpleNamespace(engine=engine)
    kernel = types.SimpleNamespace(computation=computation)
    host = types.SimpleNamespace(kernel=kernel)
    secret = "raw scar source message should not leak"

    plugin = types.SimpleNamespace(
        _hosts={"session-a": host},
        scar_dimensions_path="legacy.json",
        _read_json=lambda path, default=None: {
            "rejection": {
                "count": 1,
                "sensitivity": 1.4,
                "last_triggered": "2026-01-01T00:00:00",
                "raw": secret,
            }
        },
    )

    snapshot = build_scar_explorer_snapshot(plugin)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.scar_explorer.v1"
    assert snapshot["summary"]["topology"] == "dual_source"
    assert snapshot["summary"]["sylanne_total_scars"] == 2
    assert snapshot["summary"]["legacy_total_scars"] == 1
    assert snapshot["summary"]["active_circuit_breakers"] == 1
    assert snapshot["sessions"][0]["stage_counts"]["RAW"] == 1
    assert snapshot["sessions"][0]["stage_counts"]["SCARRED"] == 1
    assert secret not in encoded
