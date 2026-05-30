"""v0.9.7 Property 2: persona_lock 阻止核心突变写盘。"""
import asyncio
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
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub("astrbot.core.message.message_event_result", {"MessageChain": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.mixins.danger import DangerMixin  # noqa: E402


class Host(DangerMixin):
    def __init__(self, config):
        self.config = config
        self._sediment_count = 100  # 满足 %100==0，确保不是被这个挡住
        self.llm_called = False
        self.provider_queried = False

        host = self

        class _Ctx:
            async def llm_generate(self, **kw):
                host.llm_called = True
                return types.SimpleNamespace(completion_text="x")
        self.context = _Ctx()

    async def _get_provider_id(self, event=None, prefer=""):
        # 锁检查在此调用之前；被查询说明已越过 persona_lock 闸门
        self.provider_queried = True
        return ""  # 返回空 → 函数随后安全 return，无需 mock 后续依赖


class TestPersonaLock:
    def test_lock_blocks_mutation(self):
        h = Host({
            "danger_core_mutation": True,
            "danger_core_mutation_confirm": True,
            "persona_lock": True,
        })
        asyncio.run(h._danger_core_mutation(None))
        # 锁定时应在查询 provider（及任何 LLM 调用）前返回
        assert h.provider_queried is False
        assert h.llm_called is False

    def test_unlocked_proceeds_past_lock(self):
        """persona_lock=false 时不因本特性提前返回 —— 越过锁闸门去查询 provider。"""
        h = Host({
            "danger_core_mutation": True,
            "danger_core_mutation_confirm": True,
            "persona_lock": False,
        })
        asyncio.run(h._danger_core_mutation(None))
        assert h.provider_queried is True

    def test_mutation_disabled_no_call(self):
        h = Host({"danger_core_mutation": False})
        asyncio.run(h._danger_core_mutation(None))
        assert h.provider_queried is False
        assert h.llm_called is False
