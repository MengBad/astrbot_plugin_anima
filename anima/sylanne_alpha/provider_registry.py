"""AstrBot provider discovery helpers.

These helpers normalize provider objects from different AstrBot versions so
WebUI selectors and runtime provider lookup can share the same logic.
"""

from __future__ import annotations

import inspect
from typing import Any


def _provider_config(provider: Any) -> dict[str, Any]:
    config = getattr(provider, "provider_config", None)
    return config if isinstance(config, dict) else {}


def _provider_meta(provider: Any) -> Any:
    meta_fn = getattr(provider, "meta", None)
    if not callable(meta_fn):
        return None
    try:
        return meta_fn()
    except Exception:
        return None


def provider_id(provider: Any) -> str:
    meta = _provider_meta(provider)
    config = _provider_config(provider)
    candidates = (
        getattr(meta, "id", ""),
        config.get("id", ""),
        config.get("provider_id", ""),
        getattr(provider, "provider_id", ""),
        getattr(provider, "id", ""),
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def provider_name(provider: Any, fallback_id: str = "") -> str:
    meta = _provider_meta(provider)
    config = _provider_config(provider)
    candidates = (
        getattr(meta, "name", ""),
        getattr(meta, "display_name", ""),
        getattr(meta, "model_name", ""),
        getattr(meta, "model", ""),
        config.get("name", ""),
        config.get("display_name", ""),
        config.get("model_name", ""),
        config.get("model", ""),
        getattr(provider, "name", ""),
        getattr(provider, "display_name", ""),
        getattr(provider, "model_name", ""),
        getattr(provider, "model", ""),
        fallback_id,
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return fallback_id


def provider_type(provider: Any, fallback: str = "") -> str:
    meta = _provider_meta(provider)
    config = _provider_config(provider)
    candidates = (
        getattr(meta, "provider_type", ""),
        config.get("provider_type", ""),
        getattr(provider, "provider_type", ""),
        fallback,
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


async def collect_provider_items(context: Any) -> list[dict[str, Any]]:
    """Return normalized provider records for WebUI selectors."""
    items: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    def _upsert(provider: Any, inferred_type: str = "") -> None:
        pid = provider_id(provider)
        if not pid:
            return
        current = by_id.get(pid)
        ptype = provider_type(provider, inferred_type)
        name = provider_name(provider, pid)
        if current is None:
            current = {"id": pid, "name": name, "type": ptype}
            by_id[pid] = current
            return
        if name and (not current.get("name") or current["name"] == current["id"]):
            current["name"] = name
        if ptype == "embedding" or (ptype and not current.get("type")):
            current["type"] = ptype
        elif not current.get("type"):
            current["type"] = ptype

    for method_name, inferred_type in (
        ("get_all_providers", "llm"),
        ("get_all_llm_providers", "llm"),
        ("get_all_embedding_providers", "embedding"),
    ):
        getter = getattr(context, method_name, None)
        if not callable(getter):
            continue
        try:
            providers = getter()
            if inspect.isawaitable(providers):
                providers = await providers
        except Exception:
            continue
        iterable = providers.values() if isinstance(providers, dict) else (providers or [])
        for provider in iterable:
            _upsert(provider, inferred_type)

    items.extend(by_id.values())
    return items


def find_provider_by_id(context: Any, target_id: str, *, kinds: tuple[str, ...] = ("embedding", "llm")) -> Any:
    """Locate a provider object by ID across the requested provider collections."""
    pid = str(target_id or "").strip()
    if not pid:
        return None

    method_order: list[tuple[str, str]] = []
    if "embedding" in kinds:
        method_order.append(("get_all_embedding_providers", "embedding"))
    if "llm" in kinds:
        method_order.extend(
            [
                ("get_all_providers", "llm"),
                ("get_all_llm_providers", "llm"),
            ]
        )

    for method_name, _ in method_order:
        getter = getattr(context, method_name, None)
        if not callable(getter):
            continue
        try:
            providers = getter()
        except Exception:
            continue
        iterable = providers.values() if isinstance(providers, dict) else (providers or [])
        for provider in iterable:
            if provider_id(provider) == pid:
                return provider
    return None
