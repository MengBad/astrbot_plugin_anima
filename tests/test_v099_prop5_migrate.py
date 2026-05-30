"""v0.9.9 存量迁移幂等：从旧全局 worldview.json 及各 sessions/*/worldview.json
收集 social_graph/relationships 进全局 store，写迁移标记，第二次迁移为空操作。"""
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
    def __init__(self, data_dir):
        self.config = {"worldview_enabled": True, "social_graph_max": 100}
        self.data_dir = data_dir
        self._io_lock = threading.Lock()
        self.worldview_path = os.path.join(data_dir, "worldview.json")
        self.social_graph_path = os.path.join(data_dir, "social_graph.json")
        self._last_active_umo = ""


def _mk_host():
    d = tempfile.mkdtemp(prefix="anima_v099mig_")
    return Host(d)


def _seed_global_worldview(h, data):
    with open(h.worldview_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _seed_session_worldview(h, umo, data):
    d = os.path.join(h.data_dir, "sessions", h._safe_umo(umo))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "worldview.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class TestMigrate:
    def test_collects_from_global_and_sessions(self):
        h = _mk_host()
        _seed_global_worldview(h, {"environment": "旧全局", "social_graph": {"g1": "全局画像"}})
        _seed_session_worldview(h, "umo_a", {"environment": "A群", "social_graph": {"a1": "A画像"},
                                             "relationships": {"a1 -> a2": "朋友"}})
        _seed_session_worldview(h, "umo_b", {"environment": "B群", "social_graph": {"b1": "B画像"}})

        h._migrate_social_graph_v099()
        store = h._read_social_store()
        assert store["social_graph"].get("g1") == "全局画像"
        assert store["social_graph"].get("a1") == "A画像"
        assert store["social_graph"].get("b1") == "B画像"
        assert store["relationships"].get("a1 -> a2") == "朋友"
        assert store.get("migrated_v099") is True

    def test_idempotent_second_run_noop(self):
        h = _mk_host()
        _seed_global_worldview(h, {"social_graph": {"g1": "v1"}})
        h._migrate_social_graph_v099()
        # 第一次后改旧文件，第二次迁移应不再收集（已标记）
        _seed_global_worldview(h, {"social_graph": {"g1": "v2_changed", "g2": "new"}})
        h._migrate_social_graph_v099()
        store = h._read_social_store()
        assert store["social_graph"].get("g1") == "v1"
        assert "g2" not in store["social_graph"]

    def test_does_not_delete_old_data(self):
        h = _mk_host()
        _seed_global_worldview(h, {"environment": "旧全局", "social_graph": {"g1": "x"}})
        h._migrate_social_graph_v099()
        # 旧全局文件未被删除/清空
        with open(h.worldview_path, encoding="utf-8") as f:
            old = json.load(f)
        assert old["social_graph"]["g1"] == "x"
        assert old["environment"] == "旧全局"

    def test_corrupt_session_file_skipped(self):
        h = _mk_host()
        _seed_global_worldview(h, {"social_graph": {"g1": "x"}})
        d = os.path.join(h.data_dir, "sessions", h._safe_umo("umo_bad"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "worldview.json"), "w", encoding="utf-8") as f:
            f.write("{not valid json")
        # 不抛异常，仍收集到全局的 g1
        h._migrate_social_graph_v099()
        store = h._read_social_store()
        assert store["social_graph"].get("g1") == "x"
        assert store.get("migrated_v099") is True


@settings(max_examples=100)
@given(
    sg=st.dictionaries(st.text(min_size=1, max_size=6), st.text(min_size=1, max_size=6), max_size=10),
    rel=st.dictionaries(st.text(min_size=1, max_size=6), st.text(min_size=1, max_size=6), max_size=10),
)
# Feature: v099-social-graph-global, Property 5: 迁移幂等 ——
# 任意旧 worldview 数据，迁移收集进全局 store 并写标记；第二次迁移为空操作（数据不变）。
def test_prop5_migrate_idempotent(sg, rel):
    h = _mk_host()
    _seed_global_worldview(h, {"environment": "x", "social_graph": dict(sg), "relationships": dict(rel)})

    h._migrate_social_graph_v099()
    store1 = h._read_social_store()
    assert store1.get("migrated_v099") is True

    # 第二次迁移：即便改了旧文件也不应再变
    _seed_global_worldview(h, {"social_graph": {"injected": "should_not_appear"}})
    h._migrate_social_graph_v099()
    store2 = h._read_social_store()
    assert store2 == store1
    assert "injected" not in store2["social_graph"]
