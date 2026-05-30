"""v0.9.8 会话级隔离测试：umo 安全化 + worldview/time_sense per-umo 隔离 + 全局回退 + 角色本体不受影响。"""
import json
import os
import sys
import tempfile
import threading
import types

from hypothesis import given, settings, strategies as st


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

from anima.mixins.state_io import StateIOMixin  # noqa: E402
from anima.mixins.worldview import WorldviewMixin  # noqa: E402
from anima.mixins.time_sense import TimeSenseMixin  # noqa: E402


class Host(StateIOMixin, WorldviewMixin, TimeSenseMixin):
    def __init__(self, data_dir):
        self.config = {"worldview_enabled": True, "time_sense_enabled": True}
        self.data_dir = data_dir
        self._io_lock = threading.Lock()
        self.worldview_path = os.path.join(data_dir, "worldview.json")
        self.time_sense_path = os.path.join(data_dir, "time_sense.json")
        self._last_active_umo = ""


def _mk_host():
    d = tempfile.mkdtemp(prefix="anima_v098_")
    return Host(d)


class TestSafeUmo:
    def test_empty_is_default(self):
        h = _mk_host()
        assert h._safe_umo("") == "_default_"

    def test_no_path_traversal(self):
        h = _mk_host()
        for bad in ["../../etc/passwd", "a/b\\c", "..", "x/../y"]:
            safe = h._safe_umo(bad)
            assert ".." not in safe
            assert "/" not in safe and "\\" not in safe

    def test_distinct_umo_distinct_safe(self):
        h = _mk_host()
        # 替换后可能同形的两个 umo（: 和 _ 都变 _），靠哈希后缀区分
        a = h._safe_umo("group:123")
        b = h._safe_umo("group_123")
        assert a != b


@settings(max_examples=100)
@given(umo=st.text(min_size=0, max_size=40))
# Feature: v098-session-isolation, Property 1: umo 安全化安全性与唯一性 ——
# 仅含安全字符、无路径穿越、非空。
def test_prop1_safe_umo(umo):
    h = _mk_host()
    safe = h._safe_umo(umo)
    assert safe
    assert ".." not in safe
    assert "/" not in safe and "\\" not in safe
    # 仅含 [A-Za-z0-9_-]
    import re
    assert re.fullmatch(r'[A-Za-z0-9_-]+', safe)


class TestWorldviewIsolation:
    def test_distinct_umo_isolated(self):
        h = _mk_host()
        h._write_worldview({"environment": "A群"}, "umo_a")
        h._write_worldview({"environment": "B群"}, "umo_b")
        assert h._read_worldview("umo_a")["environment"] == "A群"
        assert h._read_worldview("umo_b")["environment"] == "B群"

    def test_a_write_not_seen_by_b(self):
        h = _mk_host()
        h._write_worldview({"environment": "只属于A"}, "umo_a")
        # B 无会话文件、无全局文件 → 空
        assert h._read_worldview("umo_b") == {}

    def test_global_fallback(self):
        h = _mk_host()
        # 写一个旧全局文件（模拟升级前的数据）
        with open(h.worldview_path, "w", encoding="utf-8") as f:
            json.dump({"environment": "历史全局"}, f)
        # 某 umo 首次读 → 回退全局
        assert h._read_worldview("umo_new")["environment"] == "历史全局"
        # 写入该 umo 后再读 → 读会话文件，不再回退
        h._write_worldview({"environment": "新会话"}, "umo_new")
        assert h._read_worldview("umo_new")["environment"] == "新会话"
        # 全局文件未被修改
        with open(h.worldview_path, encoding="utf-8") as f:
            assert json.load(f)["environment"] == "历史全局"


class TestTimeSenseIsolation:
    def test_distinct_umo_isolated(self):
        h = _mk_host()
        h._write_time_sense({"total_messages_today": 5, "last_interaction": {},
                             "interaction_frequency": {}, "session_start": None}, "umo_a")
        h._write_time_sense({"total_messages_today": 99, "last_interaction": {},
                             "interaction_frequency": {}, "session_start": None}, "umo_b")
        assert h._read_time_sense("umo_a")["total_messages_today"] == 5
        assert h._read_time_sense("umo_b")["total_messages_today"] == 99

    def test_default_structure_when_absent(self):
        h = _mk_host()
        ts = h._read_time_sense("umo_fresh")
        assert ts["last_interaction"] == {}
        assert ts["total_messages_today"] == 0

    def test_global_fallback(self):
        h = _mk_host()
        with open(h.time_sense_path, "w", encoding="utf-8") as f:
            json.dump({"total_messages_today": 42, "last_interaction": {},
                       "interaction_frequency": {}, "session_start": None}, f)
        assert h._read_time_sense("umo_x")["total_messages_today"] == 42


@settings(max_examples=100)
@given(
    umo_a=st.text(min_size=1, max_size=20),
    umo_b=st.text(min_size=1, max_size=20),
    val_a=st.text(min_size=1, max_size=10),
)
# Feature: v098-session-isolation, Property 2/3: 会话写入隔离 + 全局回退 ——
# 向 A 写入后读 B 不返回 A 的数据（B 无会话且无全局）。
def test_prop23_isolation(umo_a, umo_b, val_a):
    h = _mk_host()
    h._write_worldview({"environment": val_a}, umo_a)
    # 仅当 A、B 映射到不同会话目录时验证隔离
    if h._safe_umo(umo_a) != h._safe_umo(umo_b):
        assert h._read_worldview(umo_b) == {}
