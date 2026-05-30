"""v0.9.2 Property 2: 提示词与请求字段的条件化组装。"""
from hypothesis import given, settings, strategies as st

from _merged_eval_host import Host, FakeEvent


@settings(max_examples=100)
@given(
    relationship_on=st.booleans(),
    desire_on=st.booleans(),
    sylanne_state=st.sampled_from(["", "   ", "\t\n", "亲密关系，信任度高", "x" * 500]),
    user_text=st.text(min_size=0, max_size=50),
    response_text=st.text(min_size=0, max_size=50),
)
# Feature: merge-sediment-llm-calls, Property 2: 提示词与请求字段的条件化组装 —— "emotion_score" 恒在；
# "relationships" 当且仅当 relationship_on；"desire" 当且仅当 desire_on；均关时退化为纯情绪且提示词不提及关系/欲望。
def test_prop2_prompt_assembly(relationship_on, desire_on, sylanne_state, user_text, response_text):
    host = Host()
    event = FakeEvent(message_str=user_text)
    prompt, requested = host._build_merged_prompt(
        event, response_text, sylanne_state,
        relationship_on=relationship_on, desire_on=desire_on,
    )

    # emotion_score 恒在
    assert "emotion_score" in requested

    # relationships 当且仅当 relationship_on
    assert ("relationships" in requested) == relationship_on
    # desire 当且仅当 desire_on
    assert ("desire" in requested) == desire_on

    # 字段在提示词文本里的出现与 requested 一致
    assert ("relationships" in prompt) == relationship_on
    # desire 字段 JSON key 仅在请求时出现
    assert ('"desire"' in prompt) == desire_on

    # 退化为纯情绪：两者都关时 requested 只有 emotion_score，提示词不提及关系/欲望
    if not relationship_on and not desire_on:
        assert requested == frozenset({"emotion_score"})
        assert "relationships" not in prompt
        assert '"desire"' not in prompt

    # 提示词要求返回单个 JSON 对象
    assert "JSON" in prompt
