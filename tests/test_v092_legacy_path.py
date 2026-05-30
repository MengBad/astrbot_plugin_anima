"""v0.9.2 旧路径重构回归：开关关闭时三次分离调用的下游写入与埋点不变。

旧路径方法（_maybe_generate_desire / _danger_relationship_inference）重构为复用
统一下游写入函数后，外部行为应与重构前一致：仍各自发起 LLM 调用、仍 bump 各自的
埋点、下游写入结果不变。这里用混入 DesireMixin + DangerMixin + MergedEvalMixin 的
最小宿主验证。
"""
import asyncio
import sys
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(
        **{k: lambda *a, **kw: None for k in ['debug', 'info', 'warning', 'error']}
    ),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.mixins.merged_eval import MergedEvalMixin  # noqa: E402
from anima.mixins.desire import DesireMixin  # noqa: E402
from anima.mixins.danger import DangerMixin  # noqa: E402


class FakeEvent:
    def __init__(self, message_str="hi", umo="umo_a", user_id="u1"):
        self.message_str = message_str
        self.unified_msg_origin = umo
        self.message_obj = types.SimpleNamespace(
            sender=types.SimpleNamespace(user_id=user_id)
        )


class FakeLLMResp:
    def __init__(self, text):
        self.completion_text = text


class LegacyHost(MergedEvalMixin, DesireMixin, DangerMixin):
    def __init__(self, config=None):
        self.config = config or {}
        self._worldview = {}
        self._social_store = {"social_graph": {}, "relationships": {}}
        self._desires = []
        self.stats = {}
        self.desire_llm_text = "想问问对方周末去哪了"
        self.relation_llm_text = '{"u1 -> u2": "同事"}'
        self._next_text = None

        host = self

        class _Ctx:
            async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
                return FakeLLMResp(host._next_text)

        self.context = _Ctx()

    async def _get_provider_id(self, event=None, prefer=""):
        return "prov1"

    def _stat_bump(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def _is_rejected(self, text):
        return False

    async def _is_desire_already_expressed(self, d, r, event=None):
        return False

    def _read_worldview(self, umo=""):
        import copy
        return copy.deepcopy(self._worldview)

    def _write_worldview(self, data, umo=""):
        self._worldview = data

    def _read_social_store(self):
        import copy
        return copy.deepcopy(self._social_store)

    def _write_social_store(self, data):
        self._social_store = data

    def _read_desires(self):
        import copy
        return copy.deepcopy(self._desires)

    def _write_desires(self, desires):
        self._desires = desires

    @staticmethod
    def _get_event_umo(event):
        return getattr(event, "unified_msg_origin", "") or "" if event else ""


class TestLegacyDesirePath:
    def test_desire_written_and_stat_bumped(self):
        host = LegacyHost(config={"desire_enabled": True, "desire_max_queue": 5})
        host._next_text = "想问问对方周末去哪了"
        event = FakeEvent()
        asyncio.run(host._maybe_generate_desire(event, "亲密状态", "bot reply"))
        assert len(host._desires) == 1
        d = host._desires[0]
        assert d["source"] == "relationship" and d["kind"] == "outward"
        assert d["intensity"] == 0.7
        assert host.stats.get("desire.created.outward") == 1

    def test_desire_skipped_when_disabled(self):
        host = LegacyHost(config={"desire_enabled": False})
        event = FakeEvent()
        asyncio.run(host._maybe_generate_desire(event, "亲密状态", "bot reply"))
        assert host._desires == []

    def test_desire_skipped_when_no_sylanne(self):
        host = LegacyHost(config={"desire_enabled": True})
        event = FakeEvent()
        asyncio.run(host._maybe_generate_desire(event, "", "bot reply"))
        assert host._desires == []


class TestLegacyRelationshipPath:
    def test_relationship_written_and_stat_bumped(self):
        host = LegacyHost(config={
            "danger_relationship_inference": True,
            "worldview_enabled": True,
        })
        host._next_text = '{"u1 -> u2": "同事"}'
        event = FakeEvent()
        asyncio.run(host._danger_relationship_inference(event, "bot reply"))
        assert host._social_store.get("relationships", {}).get("u1 -> u2") == "同事"
        assert host.stats.get("llm.relation") == 1

    def test_relationship_skipped_when_disabled(self):
        host = LegacyHost(config={
            "danger_relationship_inference": False,
            "worldview_enabled": True,
        })
        event = FakeEvent()
        asyncio.run(host._danger_relationship_inference(event, "bot reply"))
        assert host._social_store.get("relationships", {}) == {}
        assert "llm.relation" not in host.stats
