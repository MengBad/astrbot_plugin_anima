# Feature: capability-loop-strengthening, Property 7: Layer 2 后端降级不抛异常 —— embedding 不可用降级 Jaccard
"""v0.9.10 Layer 2 属性测试 —— Property 7：后端降级不抛异常。

被测纯函数：CapabilitiesMixin._compute_capability_relevance（经 tests/_cap_host.CapHost）。

属性：对任意输入，当 `backend="embedding"` 且 `embed_fn` 为 None 或调用时抛异常时，
`_compute_capability_relevance` 降级为词法 Jaccard，返回有限非负分值，绝不抛出异常，
且降级结果与纯 lexical 路径结果完全相等（相同 best_index 与 best_score）。

降级路径与 lexical 路径共用同一个 `text_jaccard` 计算，故 best_index 与 best_score
应当**精确相等**（不是近似相等）。

Validates: Requirements 3.7
"""
import math

from hypothesis import given, settings
from hypothesis import strategies as st

from _cap_host import CapHost


def _raising_embed(text):
    """抛异常的 embed 桩：用于验证 embedding 路径任一步失败即降级、绝不抛出。"""
    raise RuntimeError("embed boom")


# 单条能力规范：name + description 必有，when_to_use 可选（None 表示缺键）。
# 文本允许空串，覆盖 Match_Text 回退（when_to_use 空白 -> description）。
_cap_spec = st.fixed_dictionaries({
    "name": st.text(max_size=12),
    "description": st.text(max_size=40),
    "when_to_use": st.one_of(st.none(), st.text(max_size=40)),
})


def _build_caps(specs):
    caps = []
    for i, spec in enumerate(specs):
        cap = {
            "id": f"cap_{i}",
            "name": spec["name"],
            "description": spec["description"],
        }
        if spec["when_to_use"] is not None:
            cap["when_to_use"] = spec["when_to_use"]
        caps.append(cap)
    return caps


@settings(max_examples=100)
@given(
    user_text=st.text(max_size=60),
    specs=st.lists(_cap_spec, min_size=0, max_size=8),
)
def test_prop7_embedding_backend_downgrades_to_lexical(user_text, specs):
    host = CapHost()
    caps = _build_caps(specs)

    # 纯 lexical 基线。
    lex_idx, lex_score = host._compute_capability_relevance(
        user_text, caps, backend="lexical"
    )

    # 变体 1：embedding 后端但 embed_fn 缺失 -> 必须降级 lexical、不抛异常。
    # 直接调用：若抛异常，pytest 失败，正是我们要检测的回归。
    idx_none, score_none = host._compute_capability_relevance(
        user_text, caps, backend="embedding", embed_fn=None
    )

    # 变体 2：embedding 后端且 embed_fn 抛异常 -> 必须捕获并降级 lexical、不抛异常。
    idx_raise, score_raise = host._compute_capability_relevance(
        user_text, caps, backend="embedding", embed_fn=_raising_embed
    )

    # 分值有限且非负（两个降级变体）。
    assert math.isfinite(score_none) and score_none >= 0.0
    assert math.isfinite(score_raise) and score_raise >= 0.0

    # 降级结果与 lexical 基线精确相等（同一 text_jaccard 路径）。
    assert idx_none == lex_idx
    assert score_none == lex_score
    assert idx_raise == lex_idx
    assert score_raise == lex_score
