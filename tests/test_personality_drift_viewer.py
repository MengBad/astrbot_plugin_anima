"""Personality Drift Viewer observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.personality import DriftAttribution, TraitMemory  # noqa: E402
from sylanne_alpha.personality_drift_viewer import (  # noqa: E402
    build_personality_drift_viewer_snapshot,
)


def test_personality_drift_viewer_snapshot_is_redacted(tmp_path):
    persona_secret = "persona core raw secret should not leak"
    mutation_secret = "mutation text should stay private"
    persona_path = tmp_path / "persona_core.yaml"
    persona_path.write_text(persona_secret, encoding="utf-8")

    attribution = DriftAttribution(maxlen=10)
    attribution.record("high_tension", "perception_acuity", 0.012, 0.61)
    comp = types.SimpleNamespace(
        _tick_count=7,
        _drift_tick=3,
        _last_drift_time=123.0,
        _drift_min_interval=30.0,
        _personality_dirty=True,
        _relationship_deltas={"session-b": {"edge": 0.1}},
        _personality={
            "warmth_bias": 0.7,
            "edge": 0.4,
            "extraversion": 0.55,
        },
        _embodiment_traits={
            "expression_drive_trait": TraitMemory(0.52),
            "perception_acuity": TraitMemory(0.61),
            "boundary_permeability": TraitMemory(0.49),
            "inner_order": TraitMemory(0.58),
            "relational_gravity": TraitMemory(0.63),
        },
        _drift_attribution=attribution,
    )
    host = types.SimpleNamespace(kernel=types.SimpleNamespace(computation=comp))
    plugin = types.SimpleNamespace(
        _hosts={"session-a": host},
        _personality_vector={
            "expressiveness": 0.6,
            "sensitivity": 0.4,
            "boundary_permeability": 0.5,
            "order_sense": 0.55,
            "relationship_gravity": 0.65,
        },
        persona_core_path=str(persona_path),
        config={"persona_lock": True, "danger_core_mutation": False},
        _load_state=lambda: {
            "mutation_history": [
                {
                    "type": "belief_shift",
                    "triggered_by": "sediment",
                    "timestamp": "2026-01-01T00:00:00",
                    "desc": mutation_secret,
                }
            ]
        },
    )

    snapshot = build_personality_drift_viewer_snapshot(plugin)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.personality_drift_viewer.v1"
    assert snapshot["summary"]["sylanne_sessions"] == 1
    assert snapshot["summary"]["recent_drift_events"] == 1
    assert snapshot["summary"]["mutation_history_count"] == 1
    assert snapshot["legacy"]["persona_core"]["content_fingerprint"]
    assert snapshot["legacy"]["mutation_history"][0]["description_fingerprint"]
    assert persona_secret not in encoded
    assert mutation_secret not in encoded
