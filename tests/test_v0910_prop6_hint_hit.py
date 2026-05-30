"""v0.9.10 Property 6: Layer 2 命中即注入、不命中不注入。"""
import math

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost

# 共享词表：让 user_text 与能力文本以一定概率共享中英文 token，从而真实触发命中
# （text_jaccard 的 tokenizer：英文长度≥3 的词 + 中文 2/3 字 ngram）。
_VOCAB = [
    "天气", "查询", "预报", "翻译", "日程", "提醒", "搜索", "笑话", "代码", "音乐",
    "weather", "translate", "calendar", "search", "music", "reminder", "joke",
]

# 由词表拼出的短语（空格分隔：中文 ngram 不依赖空格，英文需边界）。
_phrase = st.lists(st.sampled_from(_VOCAB), min_size=0, max_size=4).map(" ".join)
# 自由文本：制造低重叠 / 不命中场景。
_free = st.text(min_size=0, max_size=24)
# user_text：纯短语 / 纯自由文本 / 二者混合，覆盖命中与不命中两侧。
_user_text = st.one_of(
    _phrase,
    _free,
    st.builds(lambda a, b: (a + " " + b).strip(), _phrase, _free),
)

# 单条能力规范：name + description + 可选 when_to_use（None=缺键 / "" / 短语 / 自由文本）。
_cap_spec = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=8),
    "description": st.one_of(_phrase, _free),
    "when_to_use": st.one_of(st.none(), st.just(""), _phrase, _free),
})

# threshold 跨越 0.0（任意正分必命中）到 1.0（几乎必不命中），含显式端点。
_threshold = st.one_of(
    st.just(0.0),
    st.just(1.0),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)


@settings(max_examples=100)
@given(
    user_text=_user_text,
    specs=st.lists(_cap_spec, min_size=1, max_size=6),
    threshold=_threshold,
)
# Feature: capability-loop-strengthening, Property 6: Layer 2 命中即注入、不命中不注入
# Validates: Requirements 3.4, 3.5, 3.6
def test_prop6_hint_hit(user_text, specs, threshold):
    host = CapHost()

    # 构造非空能力集合；name 以下标前缀保证唯一且非空（便于子串断言有意义）。
    caps = []
    for i, spec in enumerate(specs):
        cap = {"name": f"{i}_{spec['name']}", "description": spec["description"]}
        if spec["when_to_use"] is not None:
            cap["when_to_use"] = spec["when_to_use"]
        caps.append(cap)

    # Oracle：直接调用真实纯函数取 (best_index, best_score)，
    # 与 _build_capability_hint 内部使用的是同一计算，杜绝重算 jaccard 引入的浮点边界假阳性。
    idx, score = host._compute_capability_relevance(user_text, caps)

    # best_index 落在合法范围（caps 非空 → 不应为 -1）。
    assert -1 <= idx < len(caps)
    assert idx >= 0
    # best_score 为有限非负 float。
    assert isinstance(score, float)
    assert math.isfinite(score)
    assert score >= 0.0

    hint = host._build_capability_hint(user_text, caps, threshold)

    # 命中判定与实现完全一致：命中 ⟺ score >= threshold（idx 已 >= 0）。
    if score >= threshold:
        # 命中：返回非空提示，且包含 argmax 能力的名称。
        assert hint != ""
        assert caps[idx]["name"] in hint
    else:
        # 不命中：返回空串，不注入任何额外 token。
        assert hint == ""
