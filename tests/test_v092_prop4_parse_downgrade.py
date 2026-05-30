"""v0.9.2 Property 4: 非法 JSON 的降级提取。"""
import json
import re

from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host


# 生成"无法被 json.loads 解析为 dict"的噪声文本
def _is_unparseable(text):
    try:
        v = json.loads(text.strip().lstrip("`"))
        return not isinstance(v, dict)
    except Exception:
        return True


@settings(max_examples=100)
@given(
    noise=st.text(
        alphabet="abcdefg 情绪分数是的没有!?，。\n模型输出乱码<>",
        min_size=0, max_size=40,
    ),
    inject_num=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
    requested=st.sampled_from([
        frozenset({"emotion_score"}),
        frozenset({"emotion_score", "relationships"}),
        frozenset({"emotion_score", "desire"}),
        frozenset({"emotion_score", "relationships", "desire"}),
    ]),
)
# Feature: merge-sediment-llm-calls, Property 4: 非法 JSON 的降级提取 ——
# 对任意无法 JSON 解析的文本，提取首个 0–1 数字（钳制）作情绪分，提不到则 0.0；
# 两种情形 relationships / desire 均为 None（跳过本轮关系与欲望）。
def test_prop4_invalid_json_downgrade(noise, inject_num, requested):
    if inject_num is not None:
        # inject_num/1000 ∈ [0,1]，固定 3 位小数，避免科学计数法干扰正则提取
        value = inject_num / 1000.0
        token = f"{value:.3f}"
        text = f"{token} {noise}"
        expected = float(token)
    else:
        # 噪声字母表不含 ASCII 数字/小数点，天然无可提取的 0-1 数
        text = noise
        expected = 0.0

    # 仅在文本确实无法解析为 dict 时才验证降级语义
    if not _is_unparseable(text):
        return

    res = host_parse(text, requested)

    # 关系与欲望恒为 None
    assert res.relationships is None
    assert res.desire is None
    # 情绪分恒落在 [0,1]
    assert 0.0 <= res.emotion_score <= 1.0
    assert abs(res.emotion_score - expected) < 1e-9


def host_parse(text, requested):
    return Host()._parse_merged_response(text, requested)
