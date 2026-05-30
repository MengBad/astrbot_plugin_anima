"""v0.9.2 Property 3: 成功解析的围栏剥离、钳制与往返。"""
import json

from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host


def _clamp(v):
    return max(0.0, min(1.0, v))


@settings(max_examples=100)
@given(
    score=st.one_of(
        st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
        st.just("__missing__"),
    ),
    want_rel=st.booleans(),
    want_desire=st.booleans(),
    rel=st.dictionaries(
        st.text(min_size=1, max_size=8), st.text(min_size=1, max_size=8), max_size=4
    ),
    desire=st.text(min_size=0, max_size=30),
    fence=st.sampled_from(["none", "json", "plain"]),
)
# Feature: merge-sediment-llm-calls, Property 3: 成功解析的围栏剥离、钳制与往返 ——
# 任意合法结果对象编码为 JSON（含/不含代码围栏）后，解析得到的情绪分等于 clamp(value,0,1)
# （缺失/非数字为 0.0）且落在 [0,1]，并正确还原 requested 中的 relationships / desire。
def test_prop3_parse_round_trip(score, want_rel, want_desire, rel, desire, fence):
    host = Host()
    requested = {"emotion_score"}
    obj = {}
    if score != "__missing__":
        obj["emotion_score"] = score
    if want_rel:
        requested.add("relationships")
        obj["relationships"] = rel
    if want_desire:
        requested.add("desire")
        obj["desire"] = desire

    raw = json.dumps(obj, ensure_ascii=False)
    if fence == "json":
        text = f"```json\n{raw}\n```"
    elif fence == "plain":
        text = f"```\n{raw}\n```"
    else:
        text = raw

    res = host._parse_merged_response(text, frozenset(requested))

    # 情绪分：缺失/非数字 → 0.0，否则 clamp
    if score == "__missing__":
        assert res.emotion_score == 0.0
    else:
        assert res.emotion_score == _clamp(score)
    assert 0.0 <= res.emotion_score <= 1.0

    # relationships 还原：仅请求且非空 dict 时填入
    if want_rel and rel:
        assert res.relationships == rel
    else:
        assert res.relationships is None

    # desire 还原：仅请求时取字符串
    if want_desire:
        assert res.desire == desire
    else:
        assert res.desire is None
