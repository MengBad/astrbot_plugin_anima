"""v0.9.4 Property 3: 硬上限不变量。"""
from datetime import datetime, timedelta

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


@settings(max_examples=100)
@given(
    n=st.integers(min_value=1, max_value=30),
    max_total=st.integers(min_value=1, max_value=20),
)
# Feature: capability-system-closed-loop, Property 3: 硬上限不变量 ——
# 维护后能力数 <= capability_max_total；被淘汰者价值分不高于被保留者中的最小值。
def test_prop3_hard_cap(n, max_total):
    now = datetime.now()
    # 构造 n 个"近期 + 已使用"的能力（避免被未使用规则淘汰），名字各异避免去重
    caps = []
    for i in range(n):
        caps.append({
            "name": f"CAP_{i:03d}_{chr(65 + i % 26)}",
            "description": f"desc number {i} alpha beta gamma {i}",
            "usage_count": (i % 5) + 1,   # >0，避免未使用淘汰
            "confidence": 0.5,
            "corrections": [],
            "last_updated": now.isoformat(),  # 新近
        })
    host = CapHost(
        config={
            "capability_system_enabled": True,
            "capability_unused_decay_days": 14,
            "capability_unused_drop_days": 30,
            "capability_max_total": max_total,
            "capability_dedup_text_threshold": 0.95,  # 调高避免误合并干扰计数
        },
        caps=caps,
    )
    host._maintain_capabilities_health()
    kept = host._read_personal_capabilities()["capabilities"]

    assert len(kept) <= max_total

    # 若发生超限淘汰，被保留者的最小价值分 >= 被淘汰者的最大价值分
    kept_names = {c["name"] for c in kept}
    dropped = [c for c in caps if c["name"] not in kept_names]
    if dropped and kept:
        min_kept = min(host._capability_value_score(c, now) for c in kept)
        max_dropped = max(host._capability_value_score(c, now) for c in dropped)
        assert min_kept >= max_dropped - 1e-9
