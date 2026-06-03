"""测试 v0.9.0 运行统计仪表盘（StatsMixin）。

验证：计数累加、跨天归零、埋点不抛异常、渲染文本包含关键分区。
"""
import sys
import types
from datetime import datetime


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

from anima.mixins.stats import StatsMixin


class _Host(StatsMixin):
    """最小宿主：用内存 dict 模拟 anima_state.json。"""
    def __init__(self):
        self.config = {"log_level": "info"}
        self._fake_state = {}

    def _load_state(self):
        return dict(self._fake_state)

    def _atomic_update_state(self, updater):
        updater(self._fake_state)


class TestStatBump:
    def test_bump_accumulates(self):
        h = _Host()
        h._stat_bump("llm.emotion")
        h._stat_bump("llm.emotion")
        h._stat_bump("llm.relation", 3)
        assert h._stats_get("llm.emotion") == 2
        assert h._stats_get("llm.relation") == 3

    def test_bump_persists_to_state(self):
        """计数应懒持久化到 state，重载后可恢复。"""
        h = _Host()
        h._stat_bump("stance.sent")
        # 模拟重载：新宿主共享同一份 state
        h2 = _Host()
        h2._fake_state = h._fake_state
        assert h2._stats_get("stance.sent") == 1

    def test_cross_day_resets(self):
        """跨天后计数归零。"""
        h = _Host()
        h._stat_bump("llm.emotion")
        # 手动把内存计数器日期改成昨天，模拟跨天
        h._stats["date"] = "2000-01-01"
        h._fake_state["stats_daily"] = {"date": "2000-01-01", "counts": {"llm.emotion": 99}}
        # 再次 bump 应识别为新的一天、归零重计
        h._stat_bump("llm.emotion")
        assert h._stats_get("llm.emotion") == 1
        assert h._stats["date"] == datetime.now().strftime("%Y-%m-%d")

    def test_bump_never_raises(self):
        """埋点失败绝不影响主流程：宿主缺 _atomic_update_state 也不抛。"""
        class _Broken(StatsMixin):
            config = {"log_level": "info"}

            def _load_state(self):
                raise RuntimeError("boom")
        b = _Broken()
        # 不应抛异常
        b._stat_bump("llm.x")
        assert b._stats_get("llm.x") in (0, 1)


class TestRenderStats:
    def test_empty(self):
        h = _Host()
        out = h._render_stats()
        assert "暂无统计数据" in out

    def test_render_contains_sections(self):
        h = _Host()
        h._stat_bump("llm.emotion", 5)
        h._stat_bump("llm.relation", 2)
        h._stat_bump("sediment.run", 3)
        h._stat_bump("sediment.skip_low", 7)
        h._stat_bump("desire.created.outward", 1)
        h._stat_bump("desire.created.inward", 4)
        h._stat_bump("stance.sent", 1)
        h._stat_bump("stance.blocked.irrelevant", 2)
        h._stat_bump("store.in", 10)
        h._stat_bump("store.out", 9)
        out = h._render_stats()
        assert "内部 LLM 调用" in out
        assert "沉淀流程" in out
        assert "主动发言" in out
        assert "记忆存储" in out
        # LLM 总数 = 5+2 = 7
        assert "共 7 次" in out
        # 拦截分项（中文标签）
        assert "话题不相关拦截" in out


class TestStatsSnapshot:
    """v0.9.1: 结构化快照（网页仪表盘数据接口的核心）。"""

    def test_empty_snapshot_shape(self):
        h = _Host()
        snap = h._stats_snapshot()
        # 结构稳定，字段齐全
        assert snap["llm_total"] == 0
        assert snap["llm_calls"] == {}
        assert snap["sediment"] == {"run": 0, "skip_low": 0}
        assert snap["desire"] == {"outward": 0, "inward": 0}
        assert snap["stance"]["sent"] == 0
        assert snap["stance"]["blocked_total"] == 0
        assert snap["store"] == {"in": 0, "out": 0}

    def test_snapshot_aggregates(self):
        h = _Host()
        h._stat_bump("llm.emotion", 5)
        h._stat_bump("llm.relation", 2)
        h._stat_bump("sediment.run", 3)
        h._stat_bump("sediment.skip_low", 7)
        h._stat_bump("desire.created.outward", 1)
        h._stat_bump("desire.created.inward", 4)
        h._stat_bump("stance.sent", 1)
        h._stat_bump("stance.blocked.irrelevant", 2)
        h._stat_bump("stance.blocked.monologue", 1)
        h._stat_bump("store.in", 10)
        h._stat_bump("store.out", 9)
        snap = h._stats_snapshot()
        assert snap["llm_total"] == 7
        assert snap["llm_calls"]["emotion"] == 5
        assert snap["llm_calls"]["relation"] == 2
        assert snap["sediment"] == {"run": 3, "skip_low": 7}
        assert snap["desire"] == {"outward": 1, "inward": 4}
        assert snap["stance"]["sent"] == 1
        assert snap["stance"]["blocked_total"] == 3
        assert snap["stance"]["blocked"]["irrelevant"] == 2
        assert snap["store"] == {"in": 10, "out": 9}

    def test_snapshot_llm_calls_sorted_desc(self):
        """llm_calls 按次数降序，方便网页直接渲染。"""
        h = _Host()
        h._stat_bump("llm.emotion", 2)
        h._stat_bump("llm.relation", 9)
        h._stat_bump("llm.worldview", 5)
        snap = h._stats_snapshot()
        values = list(snap["llm_calls"].values())
        assert values == sorted(values, reverse=True)


class TestDashboardSwitch:
    """v0.9.1: dashboard_enabled 开关 —— 关闭时埋点跳过、render 提示禁用。"""

    def test_bump_skipped_when_disabled(self):
        h = _Host()
        h.config["dashboard_enabled"] = False
        h._stat_bump("llm.emotion", 5)
        # 关闭时不累加
        assert h._stats_get("llm.emotion") == 0

    def test_bump_works_when_enabled(self):
        h = _Host()
        h.config["dashboard_enabled"] = True
        h._stat_bump("llm.emotion", 5)
        assert h._stats_get("llm.emotion") == 5

    def test_bump_default_enabled(self):
        """未显式配置时默认开（不影响现有行为）。"""
        h = _Host()
        h._stat_bump("llm.emotion", 2)
        assert h._stats_get("llm.emotion") == 2

    def test_render_shows_disabled(self):
        h = _Host()
        h.config["dashboard_enabled"] = False
        out = h._render_stats()
        assert "禁用" in out
