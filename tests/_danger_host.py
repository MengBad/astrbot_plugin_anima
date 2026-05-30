"""v0.9.5 高危功能测试共用：astrbot 桩 + 最小宿主类（混入 DangerMixin）。"""
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
_stub("astrbot.api.message_components", {"Plain": object})
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub("astrbot.core.message.message_event_result", {"MessageChain": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.mixins.danger import DangerMixin  # noqa: E402


class DangerHost(DangerMixin):
    """最小宿主：内存模拟 state / scars / desires。"""

    def __init__(self, config=None):
        self.config = config or {}
        self._state = {}
        self._scars = {}
        self._desires = []
        self._identity_stability = 1.0
        self.stats = {}

    def _load_state(self):
        import copy
        return copy.deepcopy(self._state)

    def _read_scar_dimensions(self):
        import copy
        return copy.deepcopy(self._scars)

    def _read_desires(self):
        import copy
        return copy.deepcopy(self._desires)

    def _write_desires(self, desires):
        self._desires = desires

    def _stat_bump(self, key, n=1):
        if self.config.get("dashboard_enabled", True) is False:
            return
        self.stats[key] = self.stats.get(key, 0) + n
