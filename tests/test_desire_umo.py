"""测试 v0.8.0 跨群欲望隔离（DesireMixin._filter_desires_for_umo）。

由于 DesireMixin 依赖宿主类的 self.config / self._read_json 等，
这里用最小 Mock 直接调用静态/纯逻辑函数。
"""
import sys
import types

# stub 掉 astrbot 框架，让 mixin 能 import
def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items(): setattr(m, k, v)
    sys.modules[name] = m

_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: lambda *a, **kw: None for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {
    "filter": types.SimpleNamespace(),
    "AstrMessageEvent": object,
})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})

from anima.mixins.desire import DesireMixin


class _FakeEvent:
    def __init__(self, umo: str):
        self.unified_msg_origin = umo


class TestUmoFilter:
    def test_empty_umo_returns_all(self):
        """没有 event 时（如反刍流程），返回所有 desires。"""
        m = DesireMixin()
        all_d = [
            {"id": "1", "target_umo": "groupA"},
            {"id": "2", "target_umo": "groupB"},
            {"id": "3"},  # 无 target_umo
        ]
        out = m._filter_desires_for_umo(all_d, "")
        assert len(out) == 3

    def test_match_umo_only_returns_matching_and_global(self):
        """指定 umo 时，只返回 target_umo 完全匹配 + target_umo 缺失的。"""
        m = DesireMixin()
        all_d = [
            {"id": "1", "target_umo": "groupA"},
            {"id": "2", "target_umo": "groupB"},
            {"id": "3"},  # 无 target_umo（全局通用）
            {"id": "4", "target_umo": ""},  # 显式空（同样视为全局）
        ]
        out_a = m._filter_desires_for_umo(all_d, "groupA")
        out_a_ids = {d["id"] for d in out_a}
        # groupA 应可见：1（精确匹配）, 3（无字段，旧数据）, 4（空字段）
        assert out_a_ids == {"1", "3", "4"}, f"实际 {out_a_ids}"

        out_b = m._filter_desires_for_umo(all_d, "groupB")
        out_b_ids = {d["id"] for d in out_b}
        assert out_b_ids == {"2", "3", "4"}

    def test_no_leak_between_groups(self):
        """A 群产生的执念不会出现在 B 群的查询里（v0.7.0 的真实 bug 场景）。"""
        m = DesireMixin()
        # 模拟群 A 产生的"傻逼模型"愤怒
        all_d = [
            {"id": "anger_a", "intensity": 0.8, "target_umo": "groupA",
             "content": "凭什么骂我'傻逼模型'", "satisfied": False},
            {"id": "curiosity_b", "intensity": 0.5, "target_umo": "groupB",
             "content": "想知道天气", "satisfied": False},
        ]
        # 群 B 视角看到的高强度 desires
        out_b = m._filter_desires_for_umo(all_d, "groupB")
        assert len(out_b) == 1
        assert out_b[0]["id"] == "curiosity_b"
        # 关键断言：群 A 的愤怒不该被 B 看见
        assert all(d["id"] != "anger_a" for d in out_b)


class TestEventUmoExtract:
    def test_normal_event(self):
        evt = _FakeEvent("groupA")
        assert DesireMixin._get_event_umo(evt) == "groupA"

    def test_none_event(self):
        assert DesireMixin._get_event_umo(None) == ""

    def test_event_without_umo_attr(self):
        evt = object()  # 没有 unified_msg_origin
        assert DesireMixin._get_event_umo(evt) == ""

    def test_event_with_empty_umo(self):
        evt = _FakeEvent("")
        assert DesireMixin._get_event_umo(evt) == ""
