import sys
import types
import time
import pytest

# 1. Stub the astrbot dependencies
def _stub(name, attrs=None):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m

class MockFilter:
    def on_llm_request(self, *a, **kw):
        return lambda f: f
    def on_llm_response(self, *a, **kw):
        return lambda f: f
    def command(self, *a, **kw):
        return lambda f: f
    def llm_tool(self, *a, **kw):
        return lambda f: f
    def on_using_llm_tool(self, *a, **kw):
        return lambda f: f
    def on_llm_tool_respond(self, *a, **kw):
        return lambda f: f

mock_filter = MockFilter()

_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {
    "AstrMessageEvent": object,
    "filter": mock_filter,
})
_stub("astrbot.api.provider", {
    "LLMResponse": object,
    "ProviderRequest": object,
    "TextPart": object,
})
_stub("astrbot.api.star", {
    "Context": object,
    "Star": object,
    "register": lambda *a, **kw: lambda cls: cls,
})
_stub("astrbot.core.agent.message", {"TextPart": object})
_stub("astrbot.core.agent.tool", {
    "FunctionTool": object,
    "ToolExecResult": object,
})
_stub("astrbot.core.agent.run_context", {"ContextWrapper": object})
_stub("astrbot.core.astr_agent_context", {"AstrAgentContext": object})

# 2. Import functions to test with proper package context for relative imports
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Register astrbot_plugin_anima package manually
sys.modules["astrbot_plugin_anima"] = types.ModuleType("astrbot_plugin_anima")
sys.modules["astrbot_plugin_anima"].__path__ = [str(ROOT)]

spec = importlib.util.spec_from_file_location("astrbot_plugin_anima.main", str(ROOT / "main.py"))
main_mod = importlib.util.module_from_spec(spec)
sys.modules["astrbot_plugin_anima.main"] = main_mod
main_mod.__package__ = "astrbot_plugin_anima"
spec.loader.exec_module(main_mod)

_exec_code_with_timeout = main_mod._exec_code_with_timeout
CodeExecutionTimeout = main_mod.CodeExecutionTimeout

def test_normal_execution():
    safe_globals = {"__builtins__": {"print": print}}
    local_env = {"query_or_args": "test", "result": None}
    snippet = "result = 42"
    
    _exec_code_with_timeout(snippet, safe_globals, local_env, timeout=1.0)
    assert local_env["result"] == 42

def test_infinite_loop_timeout():
    safe_globals = {"__builtins__": {}}
    local_env = {"query_or_args": "test", "result": None}
    snippet = "while True: pass"
    
    with pytest.raises(TimeoutError):
        _exec_code_with_timeout(snippet, safe_globals, local_env, timeout=0.2)

def test_try_except_exception_loop_timeout():
    safe_globals = {"__builtins__": {}}
    local_env = {"query_or_args": "test", "result": None}
    snippet = """
while True:
    try:
        pass
    except Exception:
        pass
"""
    with pytest.raises(TimeoutError):
        _exec_code_with_timeout(snippet, safe_globals, local_env, timeout=0.2)

def test_try_except_base_exception_loop_timeout():
    safe_globals = {"__builtins__": {}}
    local_env = {"query_or_args": "test", "result": None}
    snippet = """
while True:
    try:
        pass
    except BaseException:
        pass
"""
    with pytest.raises(TimeoutError):
        _exec_code_with_timeout(snippet, safe_globals, local_env, timeout=0.2)
