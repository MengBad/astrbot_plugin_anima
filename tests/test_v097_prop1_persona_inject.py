"""v0.9.7 Property 1: persona_prompt 注入 system prompt 的语义 + 幂等。"""
import sys
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from hypothesis import given, settings, strategies as st  # noqa: E402
from anima.mixins.state_io import StateIOMixin  # noqa: E402

compose = StateIOMixin._compose_system_prompt


class TestComposeBasics:
    def test_empty_persona_keeps_existing(self):
        assert compose("", "原有系统提示") == "原有系统提示"
        assert compose("   ", "原有系统提示") == "原有系统提示"

    def test_persona_prepended(self):
        out = compose("我是猫娘", "你是助手")
        assert out.startswith("我是猫娘")
        assert "你是助手" in out
        assert out == "我是猫娘\n\n你是助手"

    def test_empty_existing(self):
        assert compose("我是猫娘", "") == "我是猫娘"

    def test_idempotent_no_double_append(self):
        once = compose("我是猫娘", "你是助手")
        twice = compose("我是猫娘", once)
        assert once == twice


@settings(max_examples=100)
@given(
    persona=st.text(max_size=40),
    existing=st.text(max_size=40),
)
# Feature: v097-persona-injection, Property 1: persona_prompt 注入语义 ——
# 非空 persona 注入后以 persona 开头且包含原 system；空 persona 不变；重复注入幂等。
def test_prop1_inject_semantics(persona, existing):
    p = persona.strip()
    out = compose(persona, existing)

    if not p:
        # 空人设：原样返回 existing
        assert out == (existing or "")
        return

    # 非空人设：结果以 persona 开头（当 persona 不已在 existing 中时）
    if p in (existing or ""):
        assert out == (existing or "")
    else:
        assert out.startswith(p)
        if existing:
            assert existing in out

    # 幂等：再注入一次不变
    assert compose(persona, out) == out
