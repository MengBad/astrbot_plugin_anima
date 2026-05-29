"""测试 v0.8.6 'database is locked' 退避重试。

背景：kb.db 是 AstrBot LTM / Sylanne / Anima 多方共享的 SQLite，高并发下
单写锁会抛 OperationalError('database is locked')，这是毫秒级瞬时锁。
v0.8.6 给 _store_memory 的 upload_document 和 _query_memory 的 retrieve
加退避重试：命中锁错误就退避重试，非锁异常直接抛（保持原有行为）。
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

from anima.mixins.storage import StorageMixin


class _OperationalError(Exception):
    """模拟 sqlite3.OperationalError('database is locked')。"""


class _FlakyKB:
    """前 fail_times 次 upload_document 抛 database is locked，之后成功。"""
    def __init__(self, fail_times=0, exc_factory=None):
        self.fail_times = fail_times
        self.calls = 0
        self.uploaded = []
        self.exc_factory = exc_factory or (lambda: _OperationalError("database is locked"))

    async def upload_document(self, file_name=None, file_content=None, file_type=None, pre_chunked_text=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc_factory()
        self.uploaded.append(pre_chunked_text[0] if pre_chunked_text else "")


class _FlakyKBManager:
    """前 fail_times 次 retrieve 抛 database is locked，之后返回结果。"""
    def __init__(self, kb=None, fail_times=0, exc_factory=None):
        self._kb = kb
        self.fail_times = fail_times
        self.calls = 0
        self.exc_factory = exc_factory or (lambda: _OperationalError("database is locked"))

    async def get_kb_by_name(self, name):
        return self._kb

    async def retrieve(self, query=None, kb_names=None, top_m_final=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc_factory()
        return {"results": [{"content": "检索到的记忆"}]}


class _FakeEvent:
    def __init__(self, sender_id="user1"):
        self._sid = sender_id

    def get_sender_id(self):
        return self._sid


class _Host(StorageMixin):
    """让 StorageMixin 可独立实例化做重试单测。"""
    def __init__(self, kb=None, kb_manager=None):
        self.config = {"memory_store_interval": 30, "log_level": "info"}
        self._kb_initialized = True
        self._kb_available = True
        self._last_store_time = {}
        if kb_manager is None:
            kb_manager = _FlakyKBManager(kb)
        self.context = types.SimpleNamespace(kb_manager=kb_manager)

    # 短路掉过滤器（这些在 test_filters 里单独测）
    def _is_rejected(self, text): return False
    def _is_sensitive(self, text): return False
    def _is_injection(self, text): return False
    def _is_error_artifact(self, text): return False
    def _strip_markdown(self, text): return text

    async def _ensure_kb(self): return True


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestV086IsDbLockedError:
    def test_locked_detected(self):
        assert StorageMixin._is_db_locked_error(_OperationalError("(sqlite3.OperationalError) database is locked")) is True

    def test_case_insensitive(self):
        assert StorageMixin._is_db_locked_error(Exception("Database Is Locked")) is True

    def test_other_error_not_locked(self):
        assert StorageMixin._is_db_locked_error(Exception("no such table")) is False


class TestV086StoreRetry:
    def test_store_recovers_after_transient_lock(self):
        """前 2 次锁，第 3 次成功 —— 记忆最终应入库。"""
        kb = _FlakyKB(fail_times=2)
        host = _Host(kb=kb)
        _run(host._store_memory("会被锁两次的记忆", _FakeEvent("u1"), role="in"))
        assert kb.calls == 3  # 2 次失败 + 1 次成功
        assert any("会被锁两次的记忆" in u for u in kb.uploaded)

    def test_store_gives_up_after_max_retries(self):
        """一直锁 —— 重试耗尽后 _store_memory 的外层 try 吞掉异常，不抛出。"""
        kb = _FlakyKB(fail_times=99)
        host = _Host(kb=kb)
        # _store_memory 自身有 try/except 包住，最终不应抛异常
        _run(host._store_memory("永远锁住的记忆", _FakeEvent("u1"), role="in"))
        assert kb.calls == 4  # 1 初次 + 3 次重试
        assert kb.uploaded == []

    def test_store_non_lock_error_not_retried(self):
        """非锁异常不重试（只调用一次就抛，被外层 try 吞掉）。"""
        kb = _FlakyKB(fail_times=99, exc_factory=lambda: Exception("no such table"))
        host = _Host(kb=kb)
        _run(host._store_memory("触发非锁错误", _FakeEvent("u1"), role="in"))
        assert kb.calls == 1  # 没有重试


class TestV086QueryRetry:
    def test_query_recovers_after_transient_lock(self):
        """检索前 1 次锁，第 2 次成功 —— 最终应返回结果。"""
        mgr = _FlakyKBManager(kb=object(), fail_times=1)
        host = _Host(kb_manager=mgr)
        results = _run(host._query_memory("查点啥", n_results=3))
        assert mgr.calls == 2
        assert results == ["检索到的记忆"]

    def test_query_gives_up_after_max_retries(self):
        """检索一直锁 —— 重试耗尽后 _query_memory 返回空列表（外层 try 吞）。"""
        mgr = _FlakyKBManager(kb=object(), fail_times=99)
        host = _Host(kb_manager=mgr)
        results = _run(host._query_memory("查点啥", n_results=3))
        assert mgr.calls == 4  # 1 初次 + 3 次重试
        assert results == []

    def test_query_non_lock_error_not_retried(self):
        """检索非锁异常不重试，返回空列表。"""
        mgr = _FlakyKBManager(kb=object(), fail_times=99, exc_factory=lambda: Exception("boom"))
        host = _Host(kb_manager=mgr)
        results = _run(host._query_memory("查点啥", n_results=3))
        assert mgr.calls == 1
        assert results == []
