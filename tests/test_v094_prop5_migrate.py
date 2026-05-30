"""v0.9.4 Property 5: 存量迁移只归正未使用且幂等。"""
from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


@settings(max_examples=100)
@given(
    caps=st.lists(
        st.fixed_dictionaries({
            "usage": st.integers(min_value=0, max_value=10),
            "conf": st.floats(min_value=0.0, max_value=1.0),
        }),
        min_size=0, max_size=15,
    ),
    baseline=st.floats(min_value=0.1, max_value=0.5),
)
# Feature: capability-system-closed-loop, Property 5: 存量迁移只归正未使用且幂等 ——
# 仅把 usage==0 且 conf>baseline 的能力降到 baseline；usage>0 保留原值；不删能力；二次调用幂等。
def test_prop5_migration(caps, baseline):
    cap_list = [
        {"name": f"c{i}", "description": "d", "usage_count": c["usage"],
         "confidence": c["conf"], "corrections": []}
        for i, c in enumerate(caps)
    ]
    host = CapHost(
        config={"capability_system_enabled": True, "capability_initial_confidence": baseline},
        caps=cap_list,
    )
    # 记录每条原始期望
    expected = []
    for c in cap_list:
        if c["usage_count"] == 0 and c["confidence"] > baseline:
            expected.append(baseline)
        else:
            expected.append(c["confidence"])

    host._migrate_capabilities_v094()
    after = host._read_personal_capabilities()
    got = [c["confidence"] for c in after["capabilities"]]

    # 不删能力
    assert len(got) == len(cap_list)
    # 归正正确
    for g, e in zip(got, expected):
        assert abs(g - e) < 1e-9
    # 标记已写
    assert after["migrated_v094"] is True

    # 幂等：再跑一次不变
    snapshot = [c["confidence"] for c in host._read_personal_capabilities()["capabilities"]]
    host._migrate_capabilities_v094()
    snapshot2 = [c["confidence"] for c in host._read_personal_capabilities()["capabilities"]]
    assert snapshot == snapshot2
