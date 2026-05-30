"""v0.9.2 Property 6: 世界观关系写入与上限不变量。"""
from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host


_keys = st.text(alphabet="abcdef ->0123456789", min_size=1, max_size=10)
_vals = st.text(min_size=1, max_size=10)


@settings(max_examples=100)
@given(
    existing=st.dictionaries(_keys, _vals, max_size=40),
    candidate=st.one_of(
        st.none(),
        st.integers(),
        st.text(max_size=5),
        st.dictionaries(_keys, _vals, max_size=40),
    ),
    rejected=st.booleans(),
)
# Feature: merge-sediment-llm-calls, Property 6: 世界观关系写入与上限不变量 ——
# 候选为 None/非 dict/空 dict/命中 _is_rejected 时关系保持不变；否则 update 合并且写入后 len<=30；任何情形不抛异常。
def test_prop6_relationship_write_and_cap(existing, candidate, rejected):
    host = Host()
    host._worldview = {"relationships": dict(existing)}
    if rejected:
        # 让所有关系文本命中拒答
        host._rejected_substrings = {"{", "["}  # json.dumps 必含 { 或 空 dict {}

    before = dict(existing)

    # 不应抛异常
    host._apply_relationships_from_map(candidate)

    after = host._worldview.get("relationships", {})

    no_write = (
        candidate is None
        or not isinstance(candidate, dict)
        or len(candidate) == 0
        or rejected
    )
    if no_write:
        assert after == before
    else:
        # update 语义：候选键值应覆盖/新增
        for k, v in candidate.items():
            assert after[k] == v
        # 上限不变量
        assert len(after) <= 30
