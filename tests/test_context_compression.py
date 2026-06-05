"""测试上下文与记忆压缩相关的修复。"""

import asyncio
import sys
import types
import os
import shutil
import tempfile
from collections import deque

# Add anima path to sys.path so sylanne_alpha can be imported directly
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIMA_DIR = os.path.join(ROOT, "anima")
if ANIMA_DIR not in sys.path:
    sys.path.insert(0, ANIMA_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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

import pytest
from anima.sylanne_alpha.dialogue import WindowManager
from anima.sylanne_alpha.memory_system import MemorySystem, MemoryItem
from anima.mixins.compression import CompressionMixin
from anima.sylanne_alpha.llm_response_pipeline import LLMResponsePipeline, LocalStateInjectionBudget
from anima.sylanne_alpha.llm_request_pipeline import LLMRequestPipeline

# ============================================================================
# 1. 测试 WindowManager.compress 的时序和索引边界
# ============================================================================

class TestWindowManagerCompress:
    def test_compress_chronological_order(self):
        wm = WindowManager(max_tokens=4000)
        
        # 构造一条极长的消息使得总字数 > 8000 (估算 token > 4000)
        long_text = "a" * 9000
        messages = [
            {"role": "user", "content": long_text},   # index 0: landmark
            {"role": "assistant", "content": "msg1"}, # index 1: ephemeral
            {"role": "user", "content": "b" * 150},    # index 2: notable (len > 100)
            {"role": "assistant", "content": "msg3"}, # index 3: ephemeral
        ]
        
        importance_tags = {
            0: "landmark",
            1: "ephemeral",
            2: "notable",
            3: "ephemeral"
        }
        
        result = wm.compress(messages, importance_tags)
        
        # 期望的行为:
        # - 所有选中的消息应该保持原有的时序 (0 -> 1 -> 2 -> 3)
        # - msg 0 (landmark) 完整保留
        # - msg 1 (ephemeral) 保留（因为在最后 3 条内，i >= 4 - 3 = 1）
        # - msg 2 (notable) 被截断到 100 字符 + "…"
        # - msg 3 (ephemeral) 保留（在最后 3 条内）
        assert len(result) == 4
        assert result[0]["content"] == long_text
        assert result[1]["content"] == "msg1"
        assert result[2]["content"] == "b" * 100 + "…"
        assert result[3]["content"] == "msg3"
        
        # 确保没有修改原始 messages 列表或 notable 消息的内容
        assert len(messages[2]["content"]) == 150

    def test_compress_short_list_no_duplication(self):
        wm = WindowManager(max_tokens=4000)
        
        # 消息条数 < 3，但长度极长触发压缩
        messages = [
            {"role": "user", "content": "a" * 5000},   # index 0: landmark
            {"role": "assistant", "content": "b" * 4000}, # index 1: notable
        ]
        
        importance_tags = {
            0: "landmark",
            1: "notable"
        }
        
        result = wm.compress(messages, importance_tags)
        
        # 期望不发生越界，不发生重复，保持时序
        assert len(result) == 2
        assert result[0]["content"] == "a" * 5000
        assert result[1]["content"] == "b" * 100 + "…"


# ============================================================================
# 2. 测试 MemorySystem.compress_old_turns 的精确长度
# ============================================================================

class TestMemorySystemCompressOldTurns:
    def test_compress_old_turns_exact_length(self):
        mem = MemorySystem()
        # 注入 25 条历史消息到 L1 队中
        for i in range(25):
            mem._l1.append(MemoryItem(
                id=f"id-{i}",
                text=f"message text {i}",
                weight=0.5,
                temperature=0.0,
                age_ticks=0,
                embedding=None,
                created_at=0.0,
                source_turns=1,
                confirmed=False,
                recall_count=0,
                last_recalled_tick=0,
                rewrite_count=0,
            ))
            
        assert len(mem._l1) == 25
        
        # 运行压缩限制为 max_turns = 20
        # 25 -> 弹掉最旧的 6 个合并，最终应当是 (25-6)+1 = 20 个条目
        overflow = mem.compress_old_turns("session_a", max_turns=20)
        
        assert overflow == 6
        assert len(mem._l1) == 20
        # 确认队首被正确替换为压缩摘要
        assert mem._l1[0].text.startswith("[压缩摘要]")


# ============================================================================
# 3. 测试 CompressionMixin 对拒绝短语和敏感信息的安全拦截
# ============================================================================

class MockLlmResponse:
    def __init__(self, text):
        self.completion_text = text

class MockConfig(dict):
    def save_config(self):
        pass

class MockHost(CompressionMixin):
    def __init__(self, notes_content="initial notes"):
        self.config = MockConfig({
            "notes_max_length": 10, # 极小值以便每次都触发压缩
            "forgetting_enabled": False
        })
        self.notes = notes_content
        self.saved_config = False
        self.evolution_log = []
        self.llm_response_text = ""

        # 模拟宿主状态
        class MockCtx:
            def __init__(self, outer):
                self.outer = outer
            async def llm_generate(self, chat_provider_id, prompt):
                return MockLlmResponse(self.outer.llm_response_text)
                
        self.context = MockCtx(self)

    def _read_self_notes(self):
        return self.notes

    def _write_self_notes(self, content):
        self.notes = content

    async def _get_provider_id(self, event):
        return "mock_provider"

    def _append_evolution_log(self, trigger, old_summary, new_content):
        self.evolution_log.append((trigger, old_summary, new_content))

    def save_config(self):
        self.saved_config = True

def test_compress_notes_safety_validation():
    # 用例 1: LLM 返回拒绝短语 -> 应该被拦截，放弃写入
    host = MockHost("This is a very long note that needs to be compressed.")
    host.llm_response_text = "对此我无法进行讨论。" # 经典拒绝短语
    
    asyncio.run(host._compress_notes(None))
    
    # 验证原 notes 没被更改，也无演化日志
    assert host.notes == "This is a very long note that needs to be compressed."
    assert len(host.evolution_log) == 0

    # 用例 2: LLM 返回敏感密钥信息 -> 应该被拦截，放弃写入
    host = MockHost("This is a very long note that needs to be compressed.")
    host.llm_response_text = "my private_key is abcdef123456" # 敏感词
    
    asyncio.run(host._compress_notes(None))
    
    # 验证原 notes 没被更改，也无演化日志
    assert host.notes == "This is a very long note that needs to be compressed."
    assert len(host.evolution_log) == 0

    # 用例 3: LLM 返回正常压缩结果 -> 写入成功
    host = MockHost("This is a very long note that needs to be compressed.")
    host.llm_response_text = "我精简后的核心认知"
    
    asyncio.run(host._compress_notes(None))
    
    # 验证写入成功
    assert host.notes == "我精简后的核心认知"
    assert len(host.evolution_log) == 1


# ============================================================================
# 4. 测试 _cap_llm_request_payload 的调用和裁剪逻辑
# ============================================================================

class MockRequest:
    def __init__(self, system_prompt="", prompt=""):
        self.system_prompt = system_prompt
        self.prompt = prompt
        self.extra_user_content_parts = []
        self.contexts = []
        self.messages = []

def test_payload_capping_and_invocation():
    # 模拟 AnimaPlugin 宿主
    class MockPlugin:
        def __init__(self):
            self._config = MockConfig({
                "sylanne_alpha_locked_persona_prompt": None
            })
            # 创建 response pipeline 实例，它定义了 _cap_llm_request_payload
            self._llm_response_pipeline = LLMResponsePipeline(self)
            
    p = MockPlugin()
    
    # 构造一个极大的 request 载荷使得序列化后 > 60000 字符
    req = MockRequest(
        system_prompt="sys prompt",
        prompt="user query"
    )
    req.extra_user_content_parts = [{"text": "extra content " * 3000}]
    req.contexts = [{"role": "user", "content": "ctx " * 6000}]
    req.messages = [{"role": "assistant", "content": "msg " * 8000}]
    
    # 验证初始时序列化大小超过 60000
    import json
    orig_size = len(json.dumps(req.__dict__, ensure_ascii=False, default=str))
    assert orig_size > 60000
    
    # 直接运行裁剪
    p._llm_response_pipeline._cap_llm_request_payload(req)
    
    # 验证裁剪后满足大小限制
    capped_size = len(json.dumps(req.__dict__, ensure_ascii=False, default=str))
    assert capped_size <= 60000
    
    # 确认至少有一个部分被修剪并打上了标记
    trimmed_anywhere = (
        "[sylanne_payload_context_trimmed]" in str(req.extra_user_content_parts) or
        "[sylanne_payload_context_trimmed]" in str(req.contexts) or
        "[sylanne_payload_context_trimmed]" in str(req.messages)
    )
    assert trimmed_anywhere
