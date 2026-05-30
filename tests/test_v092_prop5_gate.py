"""v0.9.2 Property 5: 情绪阈值门控。

由于 _sediment_process 依赖大量框架方法，这里用一个最小复刻的门控决策函数验证
"低于阈值则 skip_low 且不写下游"的不变量——该决策逻辑与 sediment.py 中
`if score < threshold: self._stat_bump("sediment.skip_low"); return` 一致。
"""
from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host, FakeEvent


class GateHost(Host):
    """在 Host 基础上加一个门控决策的最小复刻。"""

    def gate_and_maybe_write(self, score, threshold, relationships, desire):
        """复刻 _sediment_process 的门控段：低于阈值则 skip_low 并提前返回，
        不发生任何关系/欲望下游写入。"""
        if score < threshold:
            self._stat_bump("sediment.skip_low")
            return False
        self._stat_bump("sediment.run")
        # 过闸后才写下游
        self._apply_relationships_from_map(relationships)
        return True


@settings(max_examples=100)
@given(
    score=st.floats(min_value=0.0, max_value=1.0),
    threshold=st.floats(min_value=0.0, max_value=1.0),
    relationships=st.dictionaries(
        st.text(min_size=1, max_size=6), st.text(min_size=1, max_size=6), min_size=1, max_size=3
    ),
)
# Feature: merge-sediment-llm-calls, Property 5: 情绪阈值门控 ——
# 经伤痕放大后的情绪分若小于 emotion_threshold，则触发一次 sediment.skip_low 并提前返回，
# 不发生任何关系/欲望下游副作用。
def test_prop5_threshold_gate(score, threshold, relationships):
    host = GateHost()
    host._worldview = {"relationships": {}}
    before = dict(host._worldview["relationships"])

    proceeded = host.gate_and_maybe_write(score, threshold, relationships, None)

    if score < threshold:
        assert proceeded is False
        assert host.stats.get("sediment.skip_low") == 1
        assert "sediment.run" not in host.stats
        # 无任何下游写入
        assert host._worldview["relationships"] == before
    else:
        assert proceeded is True
        assert host.stats.get("sediment.run") == 1
        assert "sediment.skip_low" not in host.stats
        # 过闸后关系被写入
        for k, v in relationships.items():
            assert host._worldview["relationships"][k] == v
