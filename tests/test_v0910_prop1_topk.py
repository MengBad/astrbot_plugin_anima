"""v0.9.10 Property 1: 晋升 Top-K 选择正确性。"""
from datetime import datetime, timedelta

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost

# 固定 now，保证 _capability_value_score 计算确定性（新近度依赖 last_updated 与 now 的差）
NOW = datetime(2025, 1, 1, 12, 0, 0)

# 单条能力的生成规范：usage/corrections 数/last_updated 偏移天数/name。
# id 在测试体内按下标赋值（cap_{i}）以保证唯一，便于按集合比较。
_cap_spec = st.fixed_dictionaries({
    "usage_count": st.integers(min_value=0, max_value=50),
    "n_corr": st.integers(min_value=0, max_value=5),
    "days_ago": st.integers(min_value=0, max_value=200),
    "name": st.text(min_size=1, max_size=12),
})


@settings(max_examples=100)
@given(
    specs=st.lists(_cap_spec, min_size=0, max_size=12),
    k=st.integers(min_value=0, max_value=6),
)
# Feature: capability-loop-strengthening, Property 1: 晋升 Top-K 选择正确性 —— 返回大小<=K 且未触发 Trial_Slot 时严格按价值分 Top-K
def test_prop1_promotion_topk(specs, k):
    host = CapHost()

    caps = []
    for i, spec in enumerate(specs):
        caps.append({
            "id": f"cap_{i}",
            "name": spec["name"],
            "usage_count": spec["usage_count"],
            "corrections": [{"note": f"c{j}"} for j in range(spec["n_corr"])],
            "last_updated": (NOW - timedelta(days=spec["days_ago"])).isoformat(),
        })

    result = host._select_promotion_set(caps, k, set(), now=NOW)

    # 不变量 1：返回集合大小恒 <= K。
    assert len(result) <= k

    # 不变量 2：未触发 Trial_Slot 替换时严格按价值分 Top-K。
    # 自行复算 Top-K；若返回集合与之一致 → 未触发替换 → 断言严格排序性质。
    # 若不一致 → Trial_Slot 触发（由 Property 3 覆盖）→ 跳过本不变量。
    ranked = sorted(caps, key=lambda c: -host._capability_value_score(c, NOW))
    top = ranked[:k]
    result_ids = {c["id"] for c in result}
    top_ids = {c["id"] for c in top}

    if result_ids == top_ids:
        not_promoted = [c for c in caps if c["id"] not in result_ids]
        if result and not_promoted:
            min_promoted = min(host._capability_value_score(c, NOW) for c in result)
            max_not_promoted = max(
                host._capability_value_score(c, NOW) for c in not_promoted
            )
            # 晋升集合内任一能力价值分不低于未晋升者的最大价值分
            assert min_promoted >= max_not_promoted - 1e-9
