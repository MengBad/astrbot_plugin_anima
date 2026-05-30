"""v0.9.2 Property 1: 单次物理调用纪律。"""
import asyncio

from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host, FakeEvent


@settings(max_examples=100, deadline=None)
@given(
    rel_cfg=st.booleans(),
    wv_cfg=st.booleans(),
    desire_cfg=st.booleans(),
    sylanne=st.sampled_from(["", "亲密"]),
    scenario=st.sampled_from(["ok", "timeout", "no_provider", "no_text", "raises"]),
)
# Feature: merge-sediment-llm-calls, Property 1: 单次物理调用纪律 ——
# 任意开关组合与响应/超时/空 provider 场景下，合并路径至多一次 llm_generate；当且仅当
# 物理调用完成时恰触发一次 llm.sediment_merged，且永不触发 llm.emotion/llm.relation；
# 空 provider/超时返回安全结果且不发起调用。
def test_prop1_single_physical_call(rel_cfg, wv_cfg, desire_cfg, sylanne, scenario):
    host = Host(config={
        "danger_relationship_inference": rel_cfg,
        "worldview_enabled": wv_cfg,
        "desire_enabled": desire_cfg,
    })
    host.llm_text = '{"emotion_score": 0.5}'
    if scenario == "timeout":
        host.llm_timeout = True
    elif scenario == "no_provider":
        host.provider_id = ""
    elif scenario == "no_text":
        host.llm_text = None
    elif scenario == "raises":
        host.llm_raises = RuntimeError("boom")

    event = FakeEvent()
    res = asyncio.run(host._merged_evaluate(event, "resp", sylanne))

    # 永不触发旧路径埋点
    assert "llm.emotion" not in host.stats
    assert "llm.relation" not in host.stats

    # 至多一次物理调用
    assert host.llm_call_count <= 1

    if scenario == "no_provider":
        # 不发起物理调用，安全结果，不计数
        assert host.llm_call_count == 0
        assert "llm.sediment_merged" not in host.stats
        assert res.emotion_score == 0.0
        assert res.relationships is None and res.desire is None
    elif scenario == "timeout":
        # 视为未完成物理调用：不计数、安全结果
        assert "llm.sediment_merged" not in host.stats
        assert res.emotion_score == 0.0
        assert res.relationships is None and res.desire is None
    elif scenario == "raises":
        assert "llm.sediment_merged" not in host.stats
        assert res.emotion_score == 0.0
    else:
        # ok / no_text：物理调用完成 → 恰一次计数
        assert host.llm_call_count == 1
        assert host.stats.get("llm.sediment_merged") == 1
        if scenario == "ok":
            assert res.emotion_score == 0.5
        else:  # no_text
            assert res.emotion_score == 0.0
