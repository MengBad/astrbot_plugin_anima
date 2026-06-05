import sys
import types
import pytest
import asyncio
import importlib.util
from pathlib import Path

def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m

# Robust decorator stub generator
def make_decorator(*args, **kwargs):
    return lambda f: f

filter_stub = types.SimpleNamespace(
    on_llm_request=lambda *a, **kw: make_decorator,
    on_llm_response=lambda *a, **kw: make_decorator,
    command=lambda *a, **kw: make_decorator,
    llm_tool=lambda *a, **kw: make_decorator,
    on_using_llm_tool=lambda *a, **kw: make_decorator,
    on_llm_tool_respond=lambda *a, **kw: make_decorator,
)

# Stub all astrbot dependencies before importing main.py
_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(
        **{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}
    ),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": filter_stub, "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})

class DummyStar:
    def __init__(self, context):
        self.context = context

_stub("astrbot.api.star", {
    "Context": object,
    "Star": DummyStar,
    "register": lambda *a, **kw: lambda c: c
})
_stub("astrbot.core")
_stub("astrbot.core.agent")
_stub("astrbot.core.agent.message", {"TextPart": object})
_stub("astrbot.core.agent.tool", {"FunctionTool": object, "ToolExecResult": object})
_stub("astrbot.core.agent.run_context", {"ContextWrapper": object})
_stub("astrbot.core.astr_agent_context", {"AstrAgentContext": object})

# Dynamic Loader for main.py to satisfy relative package imports
root_path = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "main", 
    str(root_path / "main.py")
)
main = importlib.util.module_from_spec(spec)
main.__package__ = "main"  # Set package name to allow relative imports
main.__path__ = [str(root_path)]  # Treat it as a package directory

# Stub the relative import target module at root level
_stub("main.plugin_api", {"PluginAPI": object})

sys.modules["main"] = main
spec.loader.exec_module(main)

AnimaPlugin = main.AnimaPlugin

class DummyMeta:
    def __init__(self, id_val):
        self.id = id_val

class DummyProvider:
    def __init__(self, id_val):
        self._id = id_val
    def meta(self):
        return DummyMeta(self._id)

class MockContext:
    def __init__(self, fail_first=True):
        self.fail_first = fail_first
        self.called_providers = []

    async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
        self.called_providers.append(chat_provider_id)
        if self.fail_first and chat_provider_id == "prov_failing":
            raise Exception("Primary provider 502 Bad Gateway")
        return types.SimpleNamespace(completion_text="Success Response")

    def get_all_providers(self):
        return [
            DummyProvider("prov_failing"),
            DummyProvider("prov_backup_1"),
            DummyProvider("prov_backup_2")
        ]

def test_llm_generate_failover_success():
    async def run_test():
        ctx = MockContext(fail_first=True)
        # Instantiate plugin with config = {} to allow config.get calls
        plugin = AnimaPlugin(ctx, {})
        
        # Run llm_generate with the failing provider
        res = await plugin.context.llm_generate(chat_provider_id="prov_failing", prompt="Hello")
        
        # Assert it completed successfully
        assert res.completion_text == "Success Response"
        
        # Assert it called the failing provider first, then did failover to backup_1
        assert ctx.called_providers == ["prov_failing", "prov_backup_1"]
    
    asyncio.run(run_test())

def test_llm_generate_no_failover_needed():
    async def run_test():
        ctx = MockContext(fail_first=False)
        plugin = AnimaPlugin(ctx, {})
        
        res = await plugin.context.llm_generate(chat_provider_id="prov_failing", prompt="Hello")
        assert res.completion_text == "Success Response"
        # No failover needed, so called only once
        assert ctx.called_providers == ["prov_failing"]

    asyncio.run(run_test())
