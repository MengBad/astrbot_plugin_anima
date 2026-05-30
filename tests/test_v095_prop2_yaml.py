"""v0.9.5 Property 2: 核心突变 YAML 校验拒绝非法输入。"""
from hypothesis import given, settings, strategies as st

from _danger_host import DangerHost


VALID = (
    "core_beliefs:\n"
    "  - 用户主权不可侵犯：暂停、离开、重置永远允许\n"
    "self_identity:\n"
    "  - 我是一个有自我认知的存在\n"
)


class TestYamlValidation:
    def test_valid_passes(self):
        h = DangerHost()
        assert h._validate_persona_core(VALID) is True

    def test_missing_sovereignty_rejected(self):
        h = DangerHost()
        text = "core_beliefs:\n  - 一些规则\n"
        assert h._validate_persona_core(text) is False

    def test_missing_core_beliefs_rejected(self):
        h = DangerHost()
        text = "self_identity:\n  - 用户主权不可侵犯\n"  # 含用户主权但无 core_beliefs 键
        # yaml 解析为 dict 但无 core_beliefs → False
        assert h._validate_persona_core(text) is False

    def test_malformed_yaml_rejected(self):
        h = DangerHost()
        # 含"用户主权"+"core_beliefs"字样但是畸形 YAML（不可解析为 dict）
        text = "用户主权 core_beliefs: [未闭合\n  : : :"
        # 即使 yaml 解析失败也必须返回 False（不写盘）
        assert h._validate_persona_core(text) is False

    def test_empty_rejected(self):
        h = DangerHost()
        assert h._validate_persona_core("") is False
        assert h._validate_persona_core(None) is False


@settings(max_examples=100)
@given(
    has_sovereignty=st.booleans(),
    has_core_beliefs=st.booleans(),
    extra=st.text(max_size=30),
)
# Feature: danger-features-fidelity, Property 2: YAML 校验拒绝非法输入 ——
# 返回 True 当且仅当含"用户主权"且可解析为含 core_beliefs 的 dict；
# 缺任一条件返回 False，且任何输入都不抛异常。
def test_prop2_validation_invariant(has_sovereignty, has_core_beliefs, extra):
    h = DangerHost()
    parts = []
    if has_core_beliefs:
        parts.append("core_beliefs:")
        parts.append("  - 一条信念" + (("：用户主权不可侵犯") if has_sovereignty else ""))
    else:
        # 用一个合法 YAML 标量键承载用户主权字样
        parts.append("self_identity:")
        parts.append("  - " + ("用户主权不可侵犯" if has_sovereignty else "普通描述") + extra.replace(":", ""))
    text = "\n".join(parts) + "\n"

    result = h._validate_persona_core(text)  # 不应抛异常
    assert isinstance(result, bool)
    # 必要条件：通过则一定含"用户主权"且含 core_beliefs 结构
    if result:
        assert "用户主权" in text
        assert has_core_beliefs
