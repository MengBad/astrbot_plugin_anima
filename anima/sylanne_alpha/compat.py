"""SylannEngine compatibility layer — bridge stubs for missing computation modules.

Provides fallback implementations for functions imported by llm_response_pipeline,
proactive_scheduler, and public_api when the full computation engine is unavailable.
Each stub returns sensible defaults so downstream code degrades gracefully.

Functions:
    strip_draft_blocks  — Strip <thinking>/<draft> blocks from LLM output
    realtime_plan       — Split response into timed message segments
    proactive_decision  — Determine whether agent should speak proactively
    command_surface     — Extract named surface view from host kernel
    simulate_update     — Dry-run emotion update without persistence
    emotion_values      — Extract current emotion dimension values
"""

from __future__ import annotations

import re
import time
from typing import Any


# ---------------------------------------------------------------------------
# strip_draft_blocks
# ---------------------------------------------------------------------------

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_DRAFT_RE = re.compile(r"<draft>.*?</draft>", re.DOTALL)


def strip_draft_blocks(text: str) -> str:
    """Remove ``<thinking>``, ``<think>``, and ``<draft>`` blocks from *text*.

    Some LLM backends emit chain-of-thought blocks in their output.
    This strips them so only the final response reaches the user.
    """
    if not text:
        return ""
    result = _THINKING_RE.sub("", text)
    result = _THINK_RE.sub("", result)
    result = _DRAFT_RE.sub("", result)
    return result.strip()


# ---------------------------------------------------------------------------
# realtime_plan
# ---------------------------------------------------------------------------

def realtime_plan(
    session_key: str,
    text: str,
    *,
    max_part_chars: int = 48,
    chars_per_second: float = 12.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Split *text* into timed message segments for simulated typing.

    Returns ``{"message_parts": [{"text": str, "delay_before_seconds": float}, ...]}``.
    Splits on sentence/clause boundaries where possible.
    """
    if not text or not text.strip():
        return {"message_parts": []}

    text = text.strip()
    cps = max(1.0, chars_per_second)
    max_chars = max(4, max_part_chars)

    parts_raw: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts_raw.append(remaining)
            break
        chunk = remaining[:max_chars]
        split_pos = -1
        for sep in ("。", "！", "？", "；", "\n", ".", "!", "?", ";", "，", ",", " "):
            idx = chunk.rfind(sep)
            if idx > 0:
                split_pos = idx + len(sep)
                break
        if split_pos <= 0:
            split_pos = max_chars
        parts_raw.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip()

    message_parts: list[dict[str, Any]] = []
    for i, part_text in enumerate(parts_raw):
        delay = 0.0 if i == 0 else len(part_text) / cps
        message_parts.append({
            "text": part_text,
            "delay_before_seconds": round(delay, 3),
        })
    return {"message_parts": message_parts}


# ---------------------------------------------------------------------------
# proactive_decision
# ---------------------------------------------------------------------------

def proactive_decision(surface: dict[str, Any]) -> dict[str, Any]:
    """Determine whether the agent should proactively speak.

    Inspects the kernel surface dict for host_payload signals.
    Returns ``{"should_speak": bool, "should_send": bool, "reason": str, "reason_code": str}``.
    """
    host_payload = surface.get("host_payload") or {}
    should_send = bool(host_payload.get("should_send", False))
    reason_code = str(host_payload.get("reason_code", ""))

    if not should_send:
        return {
            "should_speak": False,
            "should_send": False,
            "reason": "No proactive trigger detected.",
            "reason_code": reason_code or "no_trigger",
        }
    return {
        "should_speak": True,
        "should_send": True,
        "reason": f"Proactive trigger: {reason_code or 'life_rhythm'}.",
        "reason_code": reason_code or "life_rhythm",
    }


# ---------------------------------------------------------------------------
# command_surface
# ---------------------------------------------------------------------------

def command_surface(host: Any, kind: str) -> dict[str, Any]:
    """Extract a named surface view from a host's kernel.

    Delegates to ``host.kernel.surface()`` and augments with emotion data
    when *kind* is ``"emotion"``.
    """
    try:
        surface = host.kernel.surface()
    except Exception:
        surface = {}

    if kind == "emotion":
        try:
            surface["emotion"] = host.kernel.computation.engine.observe()
        except Exception:
            surface["emotion"] = {}

    return surface


# ---------------------------------------------------------------------------
# simulate_update
# ---------------------------------------------------------------------------

def simulate_update(
    host: Any,
    *,
    text: str = "",
    flags: list[str] | None = None,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Perform a dry-run emotion update on a host without persisting.

    Returns the simulated surface dict with an ``"emotion"`` key.
    """
    try:
        surface = host.kernel.surface()
    except Exception:
        surface = {}

    try:
        surface["emotion"] = host.kernel.computation.engine.observe()
    except Exception:
        surface["emotion"] = {}

    return surface


# ---------------------------------------------------------------------------
# emotion_values
# ---------------------------------------------------------------------------

_EMOTION_DIMS = (
    "warmth", "arousal", "valence", "tension",
    "curiosity", "repair_pressure", "expression_drive", "boundary_firmness",
)


def emotion_values(host: Any) -> dict[str, float]:
    """Extract current emotion dimension values from a host's kernel.

    Returns ``dict[str, float]`` with the 8 named emotion dimensions.
    Falls back to zero-valued defaults if the kernel is unavailable.
    """
    try:
        obs = host.kernel.computation.engine.observe()
        if isinstance(obs, dict):
            return {k: float(v) for k, v in obs.items() if isinstance(v, (int, float))}
    except Exception:
        pass
    return {name: 0.0 for name in _EMOTION_DIMS}
