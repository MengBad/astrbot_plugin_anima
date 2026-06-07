"""Redacted Memory Explorer snapshots for the Cognitive Observatory."""

from __future__ import annotations

import hashlib
import time
from typing import Any


MEMORY_EXPLORER_SCHEMA = "anima.memory_explorer.v1"


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _fingerprint(text: Any) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def _clamp_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _item_payload(item: Any, *, layer: str) -> dict[str, Any]:
    data = item.to_dict() if hasattr(item, "to_dict") else dict(item or {})
    text = str(data.get("text", "") or "")
    return {
        "layer": layer,
        "id": str(data.get("id", "") or "")[:12],
        "text_chars": len(text),
        "text_fingerprint": _fingerprint(text),
        "weight": _clamp_float(data.get("weight", 0.0)),
        "temperature": _clamp_float(data.get("temperature", 0.0)),
        "age_ticks": int(data.get("age_ticks", 0) or 0),
        "created_at": float(data.get("created_at", 0.0) or 0.0),
        "confirmed": bool(data.get("confirmed", False)),
        "recall_count": int(data.get("recall_count", 0) or 0),
        "rewrite_count": int(data.get("rewrite_count", 0) or 0),
        "has_embedding": bool(data.get("embedding")),
    }


def _node_payload(node: Any) -> dict[str, Any]:
    data = node.to_dict() if hasattr(node, "to_dict") else dict(node or {})
    label = str(data.get("label", "") or "")
    return {
        "id": str(data.get("id", "") or "")[:12],
        "label_chars": len(label),
        "label_fingerprint": _fingerprint(label),
        "type": str(data.get("type", "") or ""),
        "temporal_type": str(data.get("temporal_type", "") or ""),
        "clarity": _clamp_float(data.get("clarity", 0.0)),
        "emotion_weight": _clamp_float(data.get("emotion_weight", 0.0)),
        "recall_count": int(data.get("recall_count", 0) or 0),
    }


def _edge_payload(edge: Any) -> dict[str, Any]:
    data = edge.to_dict() if hasattr(edge, "to_dict") else dict(edge or {})
    relation = str(data.get("relation", "") or "")
    return {
        "source": str(data.get("source", "") or "")[:12],
        "target": str(data.get("target", "") or "")[:12],
        "relation_chars": len(relation),
        "relation_fingerprint": _fingerprint(relation),
        "clarity": _clamp_float(data.get("clarity", 0.0)),
        "emotion_weight": _clamp_float(data.get("emotion_weight", 0.0)),
        "last_recalled": int(data.get("last_recalled", 0) or 0),
    }


def _memory_system_payload(session_key: str, memory_system: Any, *, limit: int) -> dict[str, Any]:
    l1 = list(getattr(memory_system, "_l1", []) or [])
    l2 = list(getattr(memory_system, "_l2", []) or [])
    l3_nodes = dict(getattr(memory_system, "_l3_nodes", {}) or {})
    l3_edges = list(getattr(memory_system, "_l3_edges", []) or [])
    params = dict(getattr(memory_system, "_params", {}) or {})
    recalled = list(getattr(memory_system, "_recalled_l2_items", []) or [])

    l1_recent = sorted(l1, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), reverse=True)[:limit]
    l2_top = sorted(l2, key=lambda item: float(getattr(item, "weight", 0.0) or 0.0), reverse=True)[:limit]
    nodes_top = sorted(
        l3_nodes.values(),
        key=lambda node: float(getattr(node, "clarity", 0.0) or 0.0),
        reverse=True,
    )[:limit]
    edges_top = sorted(
        l3_edges,
        key=lambda edge: float(getattr(edge, "clarity", 0.0) or 0.0),
        reverse=True,
    )[:limit]

    return {
        "session_key": session_key,
        "counts": {
            "l1_hot": len(l1),
            "l2_warm": len(l2),
            "l3_nodes": len(l3_nodes),
            "l3_edges": len(l3_edges),
            "recalled_l2": len(recalled),
            "confirmed_l1": sum(1 for item in l1 if bool(getattr(item, "confirmed", False))),
            "embedding_items": sum(
                1
                for item in [*l1, *l2]
                if bool(getattr(item, "embedding", None))
            ),
        },
        "tick": int(getattr(memory_system, "_tick", 0) or 0),
        "last_consolidation_ts": float(getattr(memory_system, "_last_consolidation_ts", 0.0) or 0.0),
        "params": {
            key: _clamp_float(params.get(key, 0.0))
            for key in (
                "base_decay",
                "reconsolidation_rate",
                "compression_threshold",
                "mood_weight",
                "positive_recall_bias",
            )
        },
        "l1_recent": [_item_payload(item, layer="L1") for item in l1_recent],
        "l2_top": [_item_payload(item, layer="L2") for item in l2_top],
        "l3_top_nodes": [_node_payload(node) for node in nodes_top],
        "l3_top_edges": [_edge_payload(edge) for edge in edges_top],
    }


def build_memory_explorer_snapshot(
    plugin: Any, *, session_key: str = "", limit: int = 5
) -> dict[str, Any]:
    """Build a redacted memory topology snapshot without creating sessions."""
    limit = max(1, min(20, int(limit or 5)))
    memory_systems = getattr(plugin, "_memory_systems", {}) or {}
    sessions: list[str] = []
    if hasattr(memory_systems, "keys"):
        sessions.extend(str(key) for key in memory_systems.keys())
    if not sessions and getattr(plugin, "_memory_system", None) is not None:
        sessions.append("default")
    sessions = sorted(set(sessions))
    if session_key:
        sessions = [session for session in sessions if session == session_key]

    systems: list[dict[str, Any]] = []
    for session in sessions:
        system = memory_systems.get(session) if hasattr(memory_systems, "get") else None
        if system is None and session == "default":
            system = getattr(plugin, "_memory_system", None)
        if system is None:
            continue
        systems.append(_memory_system_payload(session, system, limit=limit))

    totals = {
        "sessions": len(systems),
        "l1_hot": sum(item["counts"]["l1_hot"] for item in systems),
        "l2_warm": sum(item["counts"]["l2_warm"] for item in systems),
        "l3_nodes": sum(item["counts"]["l3_nodes"] for item in systems),
        "l3_edges": sum(item["counts"]["l3_edges"] for item in systems),
        "recalled_l2": sum(item["counts"]["recalled_l2"] for item in systems),
        "embedding_items": sum(item["counts"]["embedding_items"] for item in systems),
    }
    return {
        "schema": MEMORY_EXPLORER_SCHEMA,
        "timestamp": time.time(),
        "redaction": {
            "text": "content omitted; text_chars and sha256 fingerprints only",
            "graph_labels": "labels omitted; label_chars and sha256 fingerprints only",
        },
        "summary": totals,
        "sessions": systems,
    }
