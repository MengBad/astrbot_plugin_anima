"""v0.9.2 路由与接线示例测试。

覆盖：_merged_evaluate 内部对各开关前置条件的计算（relationship_on/desire_on）、
_get_provider_id 接线、dashboard_enabled 关闭时埋点跳过。
_Requirements: 1.2, 4.x, 7.5, 8.2, 8.3_
"""
import asyncio

from _merged_eval_host import Host, FakeEvent


class TestProviderWiring:
    def test_uses_get_provider_id(self):
        """_merged_evaluate 经 _get_provider_id 解析模型；空串则不发起调用。"""
        host = Host()
        host.provider_id = ""
        res = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        assert host.llm_call_count == 0
        assert res.emotion_score == 0.0

    def test_calls_llm_when_provider_present(self):
        host = Host()
        host.provider_id = "prov1"
        host.llm_text = '{"emotion_score": 0.7}'
        res = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        assert host.llm_call_count == 1
        assert res.emotion_score == 0.7


class TestPreconditionRouting:
    def test_relationship_section_requires_both_switches(self):
        """关系分段需要 danger_relationship_inference 且 worldview_enabled 同时开。"""
        # 只开一个 → 关系不请求
        host = Host(config={"danger_relationship_inference": True, "worldview_enabled": False})
        host.llm_text = '{"emotion_score": 0.5, "relationships": {"a -> b": "x"}}'
        res = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        # relationships 未请求 → 即便 LLM 返回也不应被解析填入
        assert res.relationships is None

        # 两个都开 → 关系请求并解析
        host2 = Host(config={"danger_relationship_inference": True, "worldview_enabled": True})
        host2.llm_text = '{"emotion_score": 0.5, "relationships": {"a -> b": "x"}}'
        res2 = asyncio.run(host2._merged_evaluate(FakeEvent(), "resp", ""))
        assert res2.relationships == {"a -> b": "x"}

    def test_desire_section_requires_enabled_and_sylanne(self):
        host = Host(config={"desire_enabled": True})
        host.llm_text = '{"emotion_score": 0.5, "desire": "想问问"}'
        # sylanne_state 空 → 欲望不请求
        res = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        assert res.desire is None
        # sylanne_state 非空 → 欲望请求并解析
        res2 = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", "亲密"))
        assert res2.desire == "想问问"

    def test_desire_disabled_skips_even_with_sylanne(self):
        host = Host(config={"desire_enabled": False})
        host.llm_text = '{"emotion_score": 0.5, "desire": "想问问"}'
        res = asyncio.run(host._merged_evaluate(FakeEvent(), "resp", "亲密"))
        assert res.desire is None


class TestDashboardSwitch:
    def test_stat_skipped_when_dashboard_disabled(self):
        host = Host(config={"dashboard_enabled": False})
        host.llm_text = '{"emotion_score": 0.5}'
        asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        # 埋点被 _stat_bump 自身跳过
        assert "llm.sediment_merged" not in host.stats

    def test_stat_recorded_when_dashboard_enabled(self):
        host = Host(config={"dashboard_enabled": True})
        host.llm_text = '{"emotion_score": 0.5}'
        asyncio.run(host._merged_evaluate(FakeEvent(), "resp", ""))
        assert host.stats.get("llm.sediment_merged") == 1
