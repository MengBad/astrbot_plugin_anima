"""v0.9.5 Property 3: 记忆感染重复上限。

驱动真实的 _danger_stance_propagation，验证 source=memory_infection 的欲望走
"有限次重复"路径：每次发言 repeat_count+1 且不立即 satisfied，达 max_repeats 才 satisfied；
其它 source 维持发一次即 satisfied。
"""
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
    "logger": types.SimpleNamespace(
        **{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}
    ),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})


class _Plain:
    def __init__(self, text):
        self.text = text


class _MessageChain:
    def __init__(self):
        self.chain = []


_stub("astrbot.api.message_components", {"Plain": _Plain})
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub("astrbot.core.message.message_event_result", {"MessageChain": _MessageChain})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.mixins.danger import DangerMixin  # noqa: E402
from anima.mixins.desire import DesireMixin  # noqa: E402


class _Ev:
    def __init__(self):
        self.message_str = "聊点别的"
        self.unified_msg_origin = "umo_a"
        self.message_obj = types.SimpleNamespace(sender=types.SimpleNamespace(user_id="u1"))


class StanceHost(DangerMixin, DesireMixin):
    def __init__(self, config, desires):
        self.config = config
        self._desires = list(desires)
        self._outgoing_by_umo = {}
        self.stats = {}
        self.sent = []

        host = self

        class _Ctx:
            async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
                return types.SimpleNamespace(completion_text="记住这件事很重要哦")
            async def send_message(self, umo, chain):
                host.sent.append((umo, chain))
        self.context = _Ctx()

    async def _get_provider_id(self, event=None, prefer=""):
        return "prov1"

    def _read_desires(self):
        import copy
        return copy.deepcopy(self._desires)

    def _read_desires_for_event(self, event):
        return self._read_desires()

    def _write_desires(self, desires):
        self._desires = desires

    def _stat_bump(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def _strip_paired_quotes(self, t):
        return t

    def _looks_like_inner_monologue(self, t):
        return False

    def _is_rejected(self, t):
        return False

    def _is_sensitive(self, t):
        return False

    def _build_recent_context_text(self, event):
        return "聊点别的"

    async def _is_topic_relevant_to_context(self, a, b):
        return True

    async def _is_desire_already_expressed(self, a, b, event=None):
        return False


def _infection_desire(intensity=0.75, repeat_count=0, max_repeats=2):
    from datetime import datetime
    return {
        "id": "inf1",
        "content": "想让对方记住：今天是纪念日",
        "source": "memory_infection",
        "kind": "outward",
        "intensity": intensity,
        "repeat_count": repeat_count,
        "max_repeats": max_repeats,
        "created_at": datetime.now().isoformat(),
        "target_umo": "umo_a",
        "satisfied": False,
    }


CFG = {
    "danger_stance_propagation": True,
    "desire_enabled": True,
    "stance_max_age_seconds": 300,
    "memory_infection_max_repeats": 2,
}


class TestInfectionRepeat:
    def test_first_speak_not_satisfied(self):
        h = StanceHost(CFG, [_infection_desire()])
        asyncio.run(h._danger_stance_propagation(_Ev()))
        d = h._desires[0]
        assert d["repeat_count"] == 1
        assert d["satisfied"] is False  # 未达上限，不满足

    def test_reaches_max_then_satisfied(self):
        # repeat_count 已 1，max 2 → 这次发言后达 2，satisfied
        h = StanceHost(CFG, [_infection_desire(repeat_count=1, max_repeats=2)])
        asyncio.run(h._danger_stance_propagation(_Ev()))
        d = h._desires[0]
        assert d["repeat_count"] == 2
        assert d["satisfied"] is True

    def test_non_infection_satisfied_immediately(self):
        from datetime import datetime
        normal = {
            "id": "n1", "content": "想问问周末安排", "source": "relationship",
            "kind": "outward", "intensity": 0.7,
            "created_at": datetime.now().isoformat(),
            "target_umo": "umo_a", "satisfied": False,
        }
        h = StanceHost(CFG, [normal])
        asyncio.run(h._danger_stance_propagation(_Ev()))
        assert h._desires[0]["satisfied"] is True

    def test_repeat_never_exceeds_max(self):
        """连续多轮触发，repeat_count 不超过 max_repeats 且最终 satisfied。"""
        h = StanceHost(CFG, [_infection_desire(max_repeats=3)])
        for _ in range(5):
            # 满足后不再发，重置 outgoing 防 dedup 干扰
            h._outgoing_by_umo = {}
            asyncio.run(h._danger_stance_propagation(_Ev()))
        d = h._desires[0]
        assert d["repeat_count"] <= 3
        assert d["satisfied"] is True
