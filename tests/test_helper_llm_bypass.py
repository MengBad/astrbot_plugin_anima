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
def make_decorator(f):
    return f

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

class MockContext:
    def __init__(self):
        self.called_with_helper = False

    async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
        return types.SimpleNamespace(completion_text="Success Response")

def test_helper_llm_bypass_kwarg():
    async def run_test():
        ctx = MockContext()
        called_state = [None]

        async def inspect_generate(*args, **kw):
            # Assert that the ContextVar has the correct value when the actual LLM call runs!
            called_state[0] = main.in_helper_llm_call.get()
            return types.SimpleNamespace(completion_text="Success Response")

        ctx.llm_generate = inspect_generate
        plugin = AnimaPlugin(ctx, {})

        # 1. Call with _anima_helper_call=True
        await plugin.context.llm_generate(chat_provider_id="mock_prov", prompt="test", _anima_helper_call=True)
        assert called_state[0] is True

        # 2. Call normally from a non-anima module (test module)
        await plugin.context.llm_generate(chat_provider_id="mock_prov", prompt="test")
        assert called_state[0] is False

        # 3. Call from a fake anima module to test stack trace detection
        fake_globals = {"__name__": "anima.mixins.test_module", "types": types}
        # Compile async function that calls generate
        code_str = "async def call_llm(generate):\n    await generate(chat_provider_id='mock_prov', prompt='test')"
        code_obj = compile(code_str, "<string>", "exec")
        # Find the function code object inside compiled consts
        func_code = None
        for const in code_obj.co_consts:
            if isinstance(const, types.CodeType) and const.co_name == "call_llm":
                func_code = const
                break
        
        assert func_code is not None
        fake_func = types.FunctionType(func_code, fake_globals)
        await fake_func(plugin.context.llm_generate)
        assert called_state[0] is True

        assert main.in_helper_llm_call.get() is False

    asyncio.run(run_test())

def test_helper_llm_bypass_on_llm_request():
    async def run_test():
        # Setup context and plugin
        ctx = MockContext()
        plugin = AnimaPlugin(ctx, {})

        # Set the helper LLM call flag to True
        token = main.in_helper_llm_call.set(True)
        
        # We will mock _on_llm_request_inner to see if it gets called
        inner_called = [False]
        async def mock_inner(*args, **kwargs):
            inner_called[0] = True
        plugin._on_llm_request_inner = mock_inner

        event = types.SimpleNamespace(
            message_str="original message",
            unified_msg_origin="umo-test",
        )
        req = types.SimpleNamespace(
            system_prompt="before",
            prompt="after",
            extra_user_content_parts=["sentinel"],
        )

        # Trigger on_llm_request
        await plugin.on_llm_request(event, req)

        # Since helper call flag is True, on_llm_request should return early
        # and _on_llm_request_inner should not be called!
        assert not inner_called[0]
        assert req.system_prompt == "before"
        assert req.prompt == "after"
        assert req.extra_user_content_parts == ["sentinel"]

        # Reset flag to False
        main.in_helper_llm_call.reset(token)

        # Trigger on_llm_request again
        await plugin.on_llm_request(event, req)
        
        # Now it should proceed and call _on_llm_request_inner
        assert inner_called[0]

    asyncio.run(run_test())

def test_helper_llm_flag_resets_after_exception():
    async def run_test():
        ctx = MockContext()

        async def exploding_generate(*args, **kwargs):
            assert main.in_helper_llm_call.get() is True
            raise RuntimeError("boom")

        ctx.llm_generate = exploding_generate
        plugin = AnimaPlugin(ctx, {})

        with pytest.raises(RuntimeError):
            await plugin.context.llm_generate(
                chat_provider_id="mock_prov",
                prompt="test",
                _anima_helper_call=True,
            )

        assert main.in_helper_llm_call.get() is False

    asyncio.run(run_test())
