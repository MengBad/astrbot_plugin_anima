"""v0.9.4 个人能力闭环测试共用：astrbot 桩 + 最小宿主类（混入 CapabilitiesMixin）。"""
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
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
# capabilities.py 顶部 import 的 astrbot.core.agent.*
_stub("astrbot.core")
_stub("astrbot.core.agent")
_stub("astrbot.core.agent.tool", {"FunctionTool": object, "ToolExecResult": object})
_stub("astrbot.core.agent.run_context", {"ContextWrapper": object})

from anima.mixins.capabilities import CapabilitiesMixin  # noqa: E402


class CapHost(CapabilitiesMixin):
    """最小宿主：内存模拟 personal_capabilities.json。"""

    def __init__(self, config=None, caps=None):
        self.config = config or {}
        self._store = {"version": 1, "capabilities": list(caps or []), "last_research_ts": ""}
        self.evolution_log = []
        self.diary = []

    def _read_personal_capabilities(self):
        import copy
        return copy.deepcopy(self._store)

    def _write_personal_capabilities(self, data):
        self._store = data

    def _append_capabilities_diary(self, entry):
        self.diary.append(entry)

    def _append_evolution_log(self, trigger="", old_summary="", new_content=""):
        self.evolution_log.append({"trigger": trigger, "new_content": new_content})
