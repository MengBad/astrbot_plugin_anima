"""v0.9.2 Property 8: 新旧路径下游等价。

两条路径写入下游时调用同一组下游处理函数（_apply_relationships_from_map /
_apply_desire_from_text），因此对相同逻辑三元组应产出形态一致的副作用。
本测试用两个独立宿主分别模拟"旧路径产出三元组后写下游"与"合并路径产出三元组后
写下游"，断言 worldview.relationships 与欲望队列写入结果一致，且统计计数项差异
仅限 llm.sediment_merged（合并）vs llm.emotion+llm.relation（旧路径物理调用计数）。
"""
import asyncio

from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host, FakeEvent


_keys = st.text(alphabet="abcdef ->0123456789", min_size=1, max_size=8)
_vals = st.text(min_size=1, max_size=8)


@settings(max_examples=100, deadline=None)
@given(
    score=st.floats(min_value=0.0, max_value=1.0),
    relationships=st.one_of(
        st.none(),
        st.dictionaries(_keys, _vals, max_size=5),
    ),
    desire=st.one_of(st.none(), st.sampled_from(["", "无", "ab", "想约对方周末出去玩"])),
)
# Feature: merge-sediment-llm-calls, Property 8: 新旧路径下游等价 ——
# 用相同 (score, relationships, desire) 三元组分别驱动旧路径与合并路径的下游写入，
# last_emotion_score / worldview.relationships / 欲望队列写入结果一致；差异仅限统计计数项。
def test_prop8_downstream_equivalence(score, relationships, desire):
    event = FakeEvent()

    # 合并路径宿主：直接用统一写入函数
    merged = Host(config={"desire_max_queue": 5})
    merged._worldview = {"relationships": {}}
    merged._desires = []
    merged.last_emotion = score
    merged._stat_bump("llm.sediment_merged")
    merged._apply_relationships_from_map(relationships)
    asyncio.run(merged._apply_desire_from_text(desire, "bot reply", event))

    # 旧路径宿主：旧路径重构后也复用同一组写入函数，但物理调用计数走 llm.emotion/llm.relation
    legacy = Host(config={"desire_max_queue": 5})
    legacy._worldview = {"relationships": {}}
    legacy._desires = []
    legacy.last_emotion = score
    legacy._stat_bump("llm.emotion")
    if relationships:
        legacy._stat_bump("llm.relation")
    legacy._apply_relationships_from_map(relationships)
    asyncio.run(legacy._apply_desire_from_text(desire, "bot reply", event))

    # 下游副作用形态一致
    assert merged.last_emotion == legacy.last_emotion
    assert merged._worldview.get("relationships") == legacy._worldview.get("relationships")
    # 欲望队列写入结果一致（忽略 id/created_at 这类时间相关字段）
    def _norm(desires):
        return [
            {k: v for k, v in d.items() if k not in ("id", "created_at")}
            for d in desires
        ]
    assert _norm(merged._desires) == _norm(legacy._desires)

    # desire.created.outward 两路一致
    assert merged.stats.get("desire.created.outward", 0) == legacy.stats.get("desire.created.outward", 0)

    # 统计差异仅限物理调用计数项
    assert merged.stats.get("llm.sediment_merged") == 1
    assert "llm.emotion" not in merged.stats and "llm.relation" not in merged.stats
    assert legacy.stats.get("llm.emotion") == 1
    assert "llm.sediment_merged" not in legacy.stats
