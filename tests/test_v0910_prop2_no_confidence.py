"""v0.9.10 Property 2: 晋升不依赖自封置信度（解死锁）。

仅 confidence 不同的两份能力集，`_select_promotion_set` 选出的 id 集合相同 ——
证明 confidence 对晋升资格零影响。低 confidence（含 0.3 基线）只要价值分排进
Top-K 就会被纳入，仅靠高 confidence 而价值分不在 Top-K 的能力不会被晋升。

**Validates: Requirements 1.4, 2.1**
"""
import copy
from datetime import datetime, timedelta

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


# 每条能力的基础字段（不含 confidence）。usage/corrections/last_updated 决定价值分，
# 在两份能力集里逐条保持一致；只有 confidence 在两份集合里不同。
_cap_rec = st.fixed_dictionaries(
    {
        "usage_count": st.integers(min_value=0, max_value=30),
        "n_corr": st.integers(min_value=0, max_value=8),
        "day_offset": st.integers(min_value=0, max_value=200),
        # 输入空间显式包含 0.3 基线（新能力起步置信度）。
        "conf_a": st.one_of(
            st.just(0.3),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ),
        "conf_b": st.one_of(
            st.just(0.3),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ),
    }
)


@settings(max_examples=100)
@given(
    records=st.lists(_cap_rec, min_size=1, max_size=8),
    k=st.integers(min_value=1, max_value=5),
)
# Feature: capability-loop-strengthening, Property 2: 晋升不依赖自封置信度 ——
# 仅 confidence 不同的两份能力集，晋升结果 id 集合相同。
def test_prop2_promotion_ignores_confidence(records, k):
    host = CapHost()
    # 固定 now，保证价值分（含新近度衰减）计算确定。
    now = datetime(2024, 6, 1, 12, 0, 0)

    list_a = []
    list_b = []
    for i, r in enumerate(records):
        ts = (now - timedelta(days=r["day_offset"])).isoformat()
        corr = [{"ts": ts} for _ in range(r["n_corr"])]
        # 同一条 base：id / usage_count / corrections / last_updated 在 A、B 完全一致。
        cap_a = {
            "id": f"cap_{i}",
            "name": f"cap_{i}",
            "description": f"desc {i}",
            "usage_count": r["usage_count"],
            "corrections": list(corr),
            "last_updated": ts,
            "confidence": r["conf_a"],
        }
        # B 由 A 深拷贝得到，仅改动 confidence —— 两份集合"只差 confidence"。
        cap_b = copy.deepcopy(cap_a)
        conf_b = r["conf_b"]
        if conf_b == r["conf_a"]:
            # 保证 B 的 confidence 与 A 真正不同（守护 value_score 确实不读 confidence）。
            conf_b = 1.0 - conf_b if conf_b != 0.5 else 0.123
        cap_b["confidence"] = conf_b
        list_a.append(cap_a)
        list_b.append(cap_b)

    sel_a = host._select_promotion_set(list_a, k, already_promoted_ids=set(), now=now)
    sel_b = host._select_promotion_set(list_b, k, already_promoted_ids=set(), now=now)

    ids_a = {c["id"] for c in sel_a}
    ids_b = {c["id"] for c in sel_b}

    # 晋升资格完全相同：confidence 对选择零影响（解死锁）。
    assert ids_a == ids_b
    # 选择规模受 Top-K 约束，且两份集合规模一致。
    assert len(sel_a) <= k
    assert len(sel_a) == len(sel_b)
