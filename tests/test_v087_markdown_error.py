"""测试 v0.8.7：Markdown 反引号剥离 + 框架错误文本过滤。

两个生产问题：
1. 模型把颜文字用反引号/代码块包起来（```(¬_¬)```），QQ 原样显示反引号很蠢，
   且带反引号的回复被存进记忆后会被检索注入，让模型继续模仿（格式自我强化）。
2. 框架在工具调用崩溃时把 "Error occurred during AI execution..." 当成 bot
   回复记录，Anima 跟着存进记忆，下次检索被当成"我说过的话"注入污染上下文。
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
    "logger": types.SimpleNamespace(**{k: lambda *a, **kw: None for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})
_stub("astrbot.api.message_components", {"Plain": object})
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub("astrbot.core.message.message_event_result", {"MessageChain": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.filters import strip_markdown_artifacts, is_error_artifact
from anima.mixins.storage import StorageMixin


# ============ 纯函数层：strip_markdown_artifacts ============

class TestStripMarkdown:
    def test_strip_triple_backtick_kaomoji(self):
        """生产实际：```(¬_¬)``` 反引号被剥掉，颜文字保留。"""
        text = "跑分？本喵又不是安兔兔 ```(¬_¬)```"
        out = strip_markdown_artifacts(text)
        assert "`" not in out
        assert "(¬_¬)" in out
        assert "安兔兔" in out

    def test_strip_single_backtick(self):
        assert strip_markdown_artifacts("用 `code` 包起来") == "用 code 包起来"

    def test_plain_text_unchanged(self):
        text = "大半夜两点多了你还不睡，跑去床上躺着才是正经事。"
        assert strip_markdown_artifacts(text) == text

    def test_empty(self):
        assert strip_markdown_artifacts("") == ""
        assert strip_markdown_artifacts(None) is None


# ============ 纯函数层：is_error_artifact ============

class TestIsErrorArtifact:
    def test_ai_execution_error(self):
        assert is_error_artifact(
            "Error occurred during AI execution. Error Type: TypeError Error Message: sequence item 1: expected str instance, NoneType found"
        ) is True

    def test_database_locked(self):
        assert is_error_artifact("(sqlite3.OperationalError) database is locked") is True

    def test_traceback(self):
        assert is_error_artifact("Traceback (most recent call last):\n  File ...") is True

    def test_chinese_parse_fail(self):
        assert is_error_artifact("解析参数失败: Expecting value") is True

    def test_normal_reply_not_error(self):
        assert is_error_artifact("行吧行吧，你赢了，缠功一流") is False

    def test_empty(self):
        assert is_error_artifact("") is False

    def test_custom_phrases(self):
        assert is_error_artifact("自定义错误XYZ", ["自定义错误"]) is True
        assert is_error_artifact("Error occurred during AI execution", ["仅这个"]) is False


# ============ Mixin 层：存储/检索接入 ============

class _FakeKB:
    def __init__(self):
        self.uploaded = []

    async def upload_document(self, file_name=None, file_content=None, file_type=None, pre_chunked_text=None):
        self.uploaded.append(pre_chunked_text[0] if pre_chunked_text else "")


class _FakeKBManager:
    def __init__(self, kb=None, results=None):
        self._kb = kb
        self._results = results or []

    async def get_kb_by_name(self, name):
        return self._kb

    async def retrieve(self, query=None, kb_names=None, top_m_final=None):
        return {"results": [{"content": c} for c in self._results]}


class _FakeEvent:
    def __init__(self, sender_id="user1"):
        self._sid = sender_id

    def get_sender_id(self):
        return self._sid


class _Host(StorageMixin):
    """接入真实的 filters，验证存储/检索路径的过滤与剥离。"""
    def __init__(self, kb=None, kb_manager=None):
        self.config = {"memory_store_interval": 30, "log_level": "info"}
        self._kb_initialized = True
        self._kb_available = True
        self._last_store_time = {}
        if kb_manager is None:
            kb_manager = _FakeKBManager(kb)
        self.context = types.SimpleNamespace(kb_manager=kb_manager)

    # 接入真实过滤/剥离逻辑（模拟 StateIOMixin 的包装方法）
    def _is_rejected(self, text):
        from anima.filters import is_rejected
        return is_rejected(text)

    def _is_sensitive(self, text):
        from anima.filters import is_sensitive
        return is_sensitive(text)

    def _is_injection(self, text):
        from anima.filters import is_injection
        return is_injection(text)

    def _is_error_artifact(self, text):
        return is_error_artifact(text)

    def _strip_markdown(self, text):
        return strip_markdown_artifacts(text)

    async def _ensure_kb(self):
        return True


def _run(coro):
    return asyncio.run(coro)



class TestV087StorePath:
    def test_backtick_stripped_on_store(self):
        """带反引号的回复入库时反引号被剥掉。"""
        kb = _FakeKB()
        host = _Host(kb=kb)
        _run(host._store_memory("缠功一流 ```(￣▽￣)```", _FakeEvent("u1"), role="out"))
        assert len(kb.uploaded) == 1
        assert "`" not in kb.uploaded[0]
        assert "(￣▽￣)" in kb.uploaded[0]

    def test_error_artifact_not_stored(self):
        """框架错误文本不入库。"""
        kb = _FakeKB()
        host = _Host(kb=kb)
        _run(host._store_memory(
            "Error occurred during AI execution. Error Type: TypeError",
            _FakeEvent("u1"), role="out",
        ))
        assert kb.uploaded == []


class TestV087QueryPath:
    def test_error_artifact_filtered_from_query(self):
        """检索时框架错误文本被跳过（旧污染软删除）。"""
        mgr = _FakeKBManager(kb=object(), results=[
            "Error occurred during AI execution. Error Type: TypeError",
            "本喵正常的一条记忆",
        ])
        host = _Host(kb_manager=mgr)
        results = _run(host._query_memory("查询", n_results=3))
        assert "本喵正常的一条记忆" in results
        assert all("Error occurred" not in r for r in results)

    def test_backtick_stripped_from_query(self):
        """检索旧污染记忆里的反引号被剥掉。"""
        mgr = _FakeKBManager(kb=object(), results=[
            "本喵才不会自爆呢 ```(￣へ￣)```",
        ])
        host = _Host(kb_manager=mgr)
        results = _run(host._query_memory("查询", n_results=3))
        assert len(results) == 1
        assert "`" not in results[0]
        assert "(￣へ￣)" in results[0]
