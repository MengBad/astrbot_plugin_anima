"""v0.9.9 人物认知全局化：合并视图 + 写入分流 + 跨群统一 + 群环境隔离。

用临时 data_dir + 混入 StateIOMixin + WorldviewMixin 的最小宿主，验证：
- Property 1：人物认知跨群统一（A 群写 social_graph，B 群读到）
- Property 2：群环境仍按群隔离
- Property 3：写入分流正确（会话文件不含 social_graph/relationships；全局 store 含且各自上限成立）
- Property 4：合并视图等价（同时含 umo 群环境 + 全局人物认知）
"""
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


class Host(StateIOMixin, WorldviewMixin):
    def __init__(self, data_dir, social_graph_max=100):
        self.config = {"worldview_enabled": True, "social_graph_max": social_graph_max}
        self.data_dir = data_dir
        self._io_lock = threading.Lock()
        self.worldview_path = os.path.join(data_dir, "worldview.json")
        self.social_graph_path = os.path.join(data_dir, "social_graph.json")
        self._last_active_umo = ""


def _mk_host(**kw):
    d = tempfile.mkdtemp(prefix="anima_v099_")
    return Host(d, **kw)


class TestCrossGroupUnified:
    def test_social_graph_shared_across_umo(self):
        h = _mk_host()
        h._write_worldview({"environment": "A群", "social_graph": {"u1": "张三，技术宅"}}, "umo_a")
        # B 群读到同一份 social_graph
        wv_b = h._read_worldview("umo_b")
        assert wv_b["social_graph"].get("u1") == "张三，技术宅"

    def test_relationships_shared_across_umo(self):
        h = _mk_host()
        h._write_worldview({"environment": "A群", "relationships": {"u1 -> u2": "同事"}}, "umo_a")
        wv_b = h._read_worldview("umo_b")
        assert wv_b["relationships"].get("u1 -> u2") == "同事"


class TestGroupEnvIsolated:
    def test_environment_isolated(self):
        h = _mk_host()
        h._write_worldview({"environment": "A群氛围", "social_graph": {"u1": "x"}}, "umo_a")
        h._write_worldview({"environment": "B群氛围"}, "umo_b")
        assert h._read_worldview("umo_a")["environment"] == "A群氛围"
        assert h._read_worldview("umo_b")["environment"] == "B群氛围"
        # 但 social_graph 跨群统一
        assert h._read_worldview("umo_b")["social_graph"].get("u1") == "x"


class TestWriteSplit:
    def test_session_file_has_no_social_knowledge(self):
        h = _mk_host()
        h._write_worldview(
            {"environment": "技术群", "norms": "随意", "social_graph": {"u1": "a"},
             "relationships": {"u1 -> u2": "朋友"}},
            "umo_a",
        )
        # 会话文件只含群环境，不含 social_graph/relationships
        session_path = os.path.join(h.data_dir, "sessions", h._safe_umo("umo_a"), "worldview.json")
        with open(session_path, encoding="utf-8") as f:
            session_data = json.load(f)
        assert "social_graph" not in session_data
        assert "relationships" not in session_data
        assert session_data["environment"] == "技术群"
        # 全局 store 含人物认知
        store = h._read_social_store()
        assert store["social_graph"].get("u1") == "a"
        assert store["relationships"].get("u1 -> u2") == "朋友"


@settings(max_examples=100)
@given(
    umo_a=st.text(min_size=1, max_size=20),
    umo_b=st.text(min_size=1, max_size=20),
    uid=st.text(alphabet="0123456789", min_size=1, max_size=10),
    desc=st.text(min_size=1, max_size=20),
    env_a=st.text(min_size=1, max_size=20),
)
# Feature: v099-social-graph-global, Property 1+2: 人物认知跨群统一 + 群环境按群隔离 ——
# 向 A 写 social_graph[uid]=desc + environment=env_a 后，B 读到的 social_graph 含该 uid（全局），
# 而 B（不同会话且无全局）读到的 environment 为空。
def test_prop12_cross_group_unified_env_isolated(umo_a, umo_b, uid, desc, env_a):
    h = _mk_host()
    h._write_worldview({"environment": env_a, "social_graph": {uid: desc}}, umo_a)
    # 人物认知跨群统一：B 必读到
    wv_b = h._read_worldview(umo_b)
    assert wv_b["social_graph"].get(uid) == desc
    # 群环境隔离：仅当 A、B 映射到不同会话目录时验证
    if h._safe_umo(umo_a) != h._safe_umo(umo_b):
        assert wv_b.get("environment", "") == ""


@settings(max_examples=100)
@given(
    umo=st.text(min_size=1, max_size=20),
    env=st.text(min_size=0, max_size=20),
    sg=st.dictionaries(st.text(min_size=1, max_size=6), st.text(min_size=1, max_size=6), max_size=40),
    rel=st.dictionaries(st.text(min_size=1, max_size=6), st.text(min_size=1, max_size=6), max_size=40),
    cap=st.integers(min_value=1, max_value=20),
)
# Feature: v099-social-graph-global, Property 3: 写入分流正确 ——
# _write_worldview 后会话文件不含 social_graph/relationships；全局 store 含；
# social_graph<=social_graph_max，relationships<=30。
def test_prop3_write_split_and_caps(umo, env, sg, rel, cap):
    h = _mk_host(social_graph_max=cap)
    h._write_worldview({"environment": env, "social_graph": dict(sg), "relationships": dict(rel)}, umo)

    session_path = os.path.join(h.data_dir, "sessions", h._safe_umo(umo), "worldview.json")
    with open(session_path, encoding="utf-8") as f:
        session_data = json.load(f)
    assert "social_graph" not in session_data
    assert "relationships" not in session_data

    store = h._read_social_store()
    assert len(store["social_graph"]) <= cap
    assert len(store["relationships"]) <= 30
    # 上限内的键值应保留（取最近 cap / 30 条）
    if len(sg) <= cap:
        for k, v in sg.items():
            assert store["social_graph"][k] == v


@settings(max_examples=100)
@given(
    umo=st.text(min_size=1, max_size=20),
    env=st.text(min_size=1, max_size=20),
    uid=st.text(min_size=1, max_size=6),
    desc=st.text(min_size=1, max_size=10),
)
# Feature: v099-social-graph-global, Property 4: 合并视图等价 ——
# _read_worldview(umo) 同时包含该 umo 的 environment 与全局 social_graph。
def test_prop4_merged_view(umo, env, uid, desc):
    h = _mk_host()
    h._write_worldview({"environment": env, "social_graph": {uid: desc}}, umo)
    wv = h._read_worldview(umo)
    assert wv.get("environment") == env
    assert wv["social_graph"].get(uid) == desc
    assert "relationships" in wv
