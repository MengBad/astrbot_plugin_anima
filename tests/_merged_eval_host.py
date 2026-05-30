"""v0.9.2 合并评估器测试共用：astrbot 桩 + 最小宿主类。

沿用 test_v090_*.py 的 types.ModuleType 桩约定，构造一个混入 MergedEvalMixin
的最小宿主类，用内存 dict 模拟 worldview / desires / state，LLM 用可计数异步 mock。
"""
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

from anima.mixins.merged_eval import MergedEvalMixin, MergedResult  # noqa: E402


class FakeEvent:
    """最小 event：暴露 message_str / unified_msg_origin / message_obj.sender.user_id。"""
    def __init__(self, message_str="hi", umo="umo_a", user_id="u1"):
        self.message_str = message_str
        self.unified_msg_origin = umo
        self.message_obj = types.SimpleNamespace(
            sender=types.SimpleNamespace(user_id=user_id)
        )


class FakeLLMResp:
    def __init__(self, text):
        self.completion_text = text


class Host(MergedEvalMixin):
    """最小宿主：内存模拟持久化 + 可控依赖。

    可配置项：
    - config dict
    - llm_text：mock 返回的 completion_text（None 模拟无文本）
    - llm_raises：设为异常实例则 llm_generate 抛出
    - llm_timeout：True 则 llm_generate 抛 asyncio.TimeoutError
    - provider_id：_get_provider_id 返回值（""=空）
    - rejected_set / already_expressed：控制过滤行为
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._worldview = {}
        self._desires = []
        self.stats = {}
        # 可控依赖默认值
        self.llm_text = "{}"
        self.llm_raises = None
        self.llm_timeout = False
        self.provider_id = "prov1"
        self.llm_call_count = 0
        self.last_prompt = None
        self._rejected_substrings = set()
        self._already_expressed = False

        host = self

        class _Ctx:
            async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
                host.llm_call_count += 1
                host.last_prompt = prompt
                if host.llm_timeout:
                    import asyncio
                    raise asyncio.TimeoutError()
                if host.llm_raises is not None:
                    raise host.llm_raises
                if host.llm_text is None:
                    return FakeLLMResp(None)
                return FakeLLMResp(host.llm_text)

        self.context = _Ctx()

    # ── 依赖 stub ──
    async def _get_provider_id(self, event=None, prefer=""):
        return self.provider_id

    def _stat_bump(self, key, n=1):
        if self.config.get("dashboard_enabled", True) is False:
            return
        self.stats[key] = self.stats.get(key, 0) + n

    def _is_rejected(self, text):
        return any(s in (text or "") for s in self._rejected_substrings)

    async def _is_desire_already_expressed(self, desire_text, response_text, event=None):
        return self._already_expressed

    def _read_worldview(self):
        import copy
        return copy.deepcopy(self._worldview)

    def _write_worldview(self, data):
        self._worldview = data

    def _read_desires(self):
        import copy
        return copy.deepcopy(self._desires)

    def _write_desires(self, desires):
        self._desires = desires

    @staticmethod
    def _get_event_umo(event):
        if event is None:
            return ""
        return getattr(event, "unified_msg_origin", "") or ""
