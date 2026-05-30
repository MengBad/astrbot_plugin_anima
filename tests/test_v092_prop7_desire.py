"""v0.9.2 Property 7: 欲望写入的过滤与字典形态。"""
import asyncio

from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host, FakeEvent


@settings(max_examples=100)
@given(
    desire_text=st.one_of(
        st.none(),
        st.integers(),
        st.sampled_from(["", "无", "x", "ab", "想问问对方周末去哪了", "   "]),
        st.text(min_size=0, max_size=30),
    ),
    queue_len=st.integers(min_value=0, max_value=6),
    rejected=st.booleans(),
    already=st.booleans(),
)
# Feature: merge-sediment-llm-calls, Property 7: 欲望写入的过滤与字典形态 ——
# 当且仅当 未命中拒答 且 非退化值 且 未表达过 且 队列未满 时写入一条欲望并恰触发一次
# desire.created.outward；写入字典字段恒为约定形态；任一不满足则不写不计数。
def test_prop7_desire_write(desire_text, queue_len, rejected, already):
    host = Host(config={"desire_max_queue": 5})
    host._desires = [{"id": f"d{i}", "content": f"c{i}"} for i in range(queue_len)]
    host._already_expressed = already
    if rejected:
        host._rejected_substrings = {"x", "想", "a", " ", "无"}  # 尽量命中各类候选

    event = FakeEvent()
    before = list(host._desires)

    asyncio.run(host._apply_desire_from_text(desire_text, "bot reply", event))

    # 计算期望是否写入
    is_str = isinstance(desire_text, str)
    stripped = desire_text.strip() if is_str else ""
    degenerate = (not is_str) or (not stripped) or stripped == "无" or len(stripped) <= 2
    hit_reject = is_str and host._is_rejected(stripped)
    queue_full = queue_len >= 5

    should_write = (not degenerate) and (not hit_reject) and (not queue_full) and (not already)

    if should_write:
        assert len(host._desires) == len(before) + 1
        d = host._desires[-1]
        assert d["source"] == "relationship"
        assert d["kind"] == "outward"
        assert d["intensity"] == 0.7
        assert d["satisfied"] is False
        assert d["content"] == stripped
        assert "id" in d and "created_at" in d
        assert "target_user" in d and "target_umo" in d
        assert host.stats.get("desire.created.outward", 0) == 1
    else:
        assert len(host._desires) == len(before)
        assert host.stats.get("desire.created.outward", 0) == 0
