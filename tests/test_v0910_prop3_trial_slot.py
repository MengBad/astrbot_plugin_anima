# Feature: capability-loop-strengthening, Property 3: Trial_Slot 保证新能力可见 —— K>=1 时晋升集合至少含一个未晋升的 usage==0 新能力
"""v0.9.10 Layer 1 属性测试 —— Property 3：Trial_Slot 保证新能力可见。

被测纯函数：CapabilitiesMixin._select_promotion_set（经 tests/_cap_host.CapHost）。

属性：对任意同时包含「高价值老能力」（usage_count >= 1，故非新能力）与
「至少一个 usage_count==0 且 id 不在 already_promoted_ids 的新能力」的集合，
当 K >= 1 时，_select_promotion_set 的返回集合至少含一个这样的新能力
（占用 Trial_Slot）。

关键微妙点：老能力的 Value_Score 被构造得足够高（usage_count >= 3 → 分值 >= 6，
而新能力上界为 corr*0.5 + recency <= 2.0），使老能力在 n_old >= K 时填满全部
Top-K 槽位，从而真正触发 Trial_Slot 的替换逻辑，而非让新能力"恰好"自然进入。

Validates: Requirements 1.5
"""
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from _cap_host import CapHost

# 固定时间，保证 _capability_value_score 的新近度计算确定。
NOW = datetime(2024, 6, 1, 12, 0, 0)


def _last_updated(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


@st.composite
def trial_slot_scenario(draw):
    """构造：>=1 个高价值老能力 + >=1 个新能力，id 全局唯一。

    - 老能力：usage_count >= 3（分值 >= 6），故既非新能力、又能压制新能力价值分。
    - 新能力：usage_count == 0，id 形如 new_{j}，不在 already_promoted_ids 内。
    - already_promoted_ids：仅取自老能力 id 的子集（可空），确保新能力始终保持
      "未晋升"身份。
    - K：1..6。
    - 最终对合并列表做随机置换，打散原始顺序以覆盖稳定排序路径。
    """
    n_old = draw(st.integers(min_value=1, max_value=6))
    n_new = draw(st.integers(min_value=1, max_value=4))
    k = draw(st.integers(min_value=1, max_value=6))

    old_caps = []
    for i in range(n_old):
        old_caps.append({
            "id": f"old_{i}",
            "name": f"老能力{i}",
            "description": "老能力描述",
            # usage_count >= 3 → value_score >= 6.0，远高于新能力上界 2.0
            "usage_count": draw(st.integers(min_value=3, max_value=50)),
            "corrections": ["c"] * draw(st.integers(min_value=0, max_value=5)),
            "last_updated": _last_updated(draw(st.integers(min_value=0, max_value=120))),
        })

    new_caps = []
    for j in range(n_new):
        new_caps.append({
            "id": f"new_{j}",
            "name": f"新能力{j}",
            "description": "新能力描述",
            "usage_count": 0,  # 新能力：从未被使用
            "corrections": ["c"] * draw(st.integers(min_value=0, max_value=2)),
            "last_updated": _last_updated(draw(st.integers(min_value=0, max_value=120))),
        })

    # already_promoted_ids 仅含老能力 id（子集），不污染新能力身份。
    old_ids = [c["id"] for c in old_caps]
    promoted = set(draw(st.lists(st.sampled_from(old_ids), unique=True)))

    caps = draw(st.permutations(old_caps + new_caps))
    return list(caps), k, promoted


@settings(max_examples=100)
@given(trial_slot_scenario())
def test_trial_slot_guarantees_newcomer_visible(scenario):
    caps, k, promoted = scenario
    host = CapHost()

    result = host._select_promotion_set(caps, k, promoted, now=NOW)

    has_newcomer = any(
        (c.get("usage_count", 0) or 0) == 0 and c.get("id") not in promoted
        for c in result
    )
    assert has_newcomer, (
        "Trial_Slot 失效：K>=1 时晋升集合未含任何未晋升的 usage==0 新能力。"
        f" k={k}, promoted={sorted(promoted)},"
        f" result_ids={[c.get('id') for c in result]}"
    )
