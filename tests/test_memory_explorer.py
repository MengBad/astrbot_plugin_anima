"""Memory Explorer observability tests."""

import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.memory_explorer import build_memory_explorer_snapshot  # noqa: E402
from sylanne_alpha.memory_system import GraphEdge, GraphNode, MemoryItem, MemorySystem  # noqa: E402


def test_memory_explorer_snapshot_is_redacted():
    secret_text = "private memory body should not leak"
    secret_label = "secret graph label"
    secret_relation = "secret relation"
    memory = MemorySystem()
    item = MemoryItem(
        id="item-secret",
        text=secret_text,
        weight=0.8,
        temperature=0.2,
        age_ticks=3,
        embedding=[0.1, 0.2],
        created_at=123.0,
        confirmed=True,
        recall_count=2,
        rewrite_count=1,
    )
    memory._l1.append(item)
    memory._l2.append(item)
    memory._l3_nodes["n1"] = GraphNode(
        id="n1",
        label=secret_label,
        type="topic",
        temporal_type="episodic",
        emotion_weight=0.3,
        clarity=0.9,
    )
    memory._l3_edges.append(GraphEdge(
        source="n1",
        target="n2",
        relation=secret_relation,
        emotion_weight=0.2,
        clarity=0.7,
    ))

    plugin = types.SimpleNamespace(_memory_systems={"session-a": memory})
    snapshot = build_memory_explorer_snapshot(plugin)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.memory_explorer.v1"
    assert snapshot["summary"]["l1_hot"] == 1
    assert snapshot["summary"]["l2_warm"] == 1
    assert snapshot["summary"]["l3_nodes"] == 1
    assert "text_fingerprint" in snapshot["sessions"][0]["l1_recent"][0]
    assert secret_text not in encoded
    assert secret_label not in encoded
    assert secret_relation not in encoded
