"""v0.9.4 Property 2: 未使用能力的退场单调性。"""
from datetime import datetime, timedelta

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


def _cap(name, usage, conf, age_days):
    ts = (datetime.now() - timedelta(days=age_days)).isoformat()
    return {"name": name, "description": "d", "usage_count": usage,
            "confidence": conf, "corrections": [], "last_updated": ts}


@settings(max_examples=100)
@given(
    age=st.integers(min_value=0, max_value=120),
    conf=st.floats(min_value=0.0, max_value=1.0),
    usage=st.integers(min_value=0, max_value=3),
    decay=st.integers(min_value=5, max_value=20),
    drop=st.integers(min_value=21, max_value=60),
)
# Feature: capability-system-closed-loop, Property 2: 未使用能力的退场单调性 ——
# usage==0 且 days>drop → 淘汰；usage==0 且 decay<days<=drop → 置信度*0.9（下限0.05）；
# 这两类判定不依赖能力当前 confidence。
def test_prop2_unused_exit(age, conf, usage, decay, drop):
    # 用一个独特名字，避免与去重逻辑交互
    host = CapHost(
        config={
            "capability_system_enabled": True,
            "capability_unused_decay_days": decay,
            "capability_unused_drop_days": drop,
            "capability_max_total": 999,
            "capability_dedup_text_threshold": 0.99,
        },
        caps=[_cap("UNIQUE_CAP_X", usage, conf, age)],
    )
    host._maintain_capabilities_health()
    kept = host._read_personal_capabilities()["capabilities"]

    if usage == 0 and age > drop:
        # 淘汰（除非也命中旧低价值规则，结果一致：被移除）
        assert len(kept) == 0
    elif usage == 0 and age > decay:
        # 降权（若未同时被旧规则 conf<0.2&usage<=1&age>25 淘汰）
        if conf < 0.2 and usage <= 1 and age > 25:
            assert len(kept) == 0  # 旧规则淘汰
        else:
            assert len(kept) == 1
            assert abs(kept[0]["confidence"] - max(0.05, conf * 0.9)) < 1e-9
    else:
        # 未触发未使用规则；仍可能命中旧低价值淘汰
        if conf < 0.2 and usage <= 1 and age > 25:
            assert len(kept) == 0
        else:
            assert len(kept) == 1
