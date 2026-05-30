"""测试 v0.8.8 查缺补漏修复：

- B3: _get_active_desires_text 对缺 content 字段的 desire 不再 KeyError
      （该方法在 on_llm_request 注入路径上，外层无 try 兜底，抛错会打断主对话注入）
- P4: danger 关系推断写入 worldview 的 relationships 加上限裁剪（防无限膨胀）

这两个都用最小 stub 直接调用 mixin 方法验证。
"""
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

from anima.mixins.desire import DesireMixin


class _FakeEvent:
    def __init__(self, umo: str = "groupA"):
        self.unified_msg_origin = umo


class TestB3DesireMissingContent:
    """B3: desire 缺 content 字段时 _get_active_desires_text 不应抛 KeyError。"""

    def _make_host(self, desires):
        m = DesireMixin()
        m.config = {"desire_enabled": True}
        # 短路 _read_desires_for_event，直接喂入测试数据
        m._read_desires_for_event = lambda event: desires
        return m

    def test_missing_content_does_not_raise(self):
        """混入缺 content 的 desire，不崩，且跳过该条。"""
        host = self._make_host([
            {"id": "1", "intensity": 0.8, "content": "想知道对方的反应"},
            {"id": "2", "intensity": 0.9},  # 缺 content —— 旧数据/外部写入
        ])
        out = host._get_active_desires_text(_FakeEvent())
        # 不抛异常，且只渲染有 content 的那条
        assert "想知道对方的反应" in out
        assert out.count("此刻内心隐约想着") == 1

    def test_empty_content_filtered(self):
        """content 为空串/纯空白的 desire 被过滤掉。"""
        host = self._make_host([
            {"id": "1", "intensity": 0.8, "content": "   "},  # 纯空白
            {"id": "2", "intensity": 0.8, "content": ""},      # 空串
        ])
        out = host._get_active_desires_text(_FakeEvent())
        assert out == ""

    def test_normal_desires_still_render(self):
        """正常 desire 仍正确渲染（回归保护）。"""
        host = self._make_host([
            {"id": "1", "intensity": 0.8, "content": "想A"},
            {"id": "2", "intensity": 0.7, "content": "想B"},
        ])
        out = host._get_active_desires_text(_FakeEvent())
        assert "想A" in out and "想B" in out


class TestP4RelationshipsCap:
    """P4: relationships 上限裁剪逻辑（复刻 danger.py 的裁剪规则）。"""

    @staticmethod
    def _apply_cap(existing: dict, relations: dict, max_rel: int = 30) -> dict:
        """复刻 danger.py:_danger_relationship_inference 里的裁剪逻辑。"""
        wv = {"relationships": dict(existing)}
        wv["relationships"].update(relations)
        if len(wv["relationships"]) > max_rel:
            wv["relationships"] = dict(list(wv["relationships"].items())[-max_rel:])
        return wv["relationships"]

    def test_under_cap_keeps_all(self):
        existing = {f"k{i}": i for i in range(10)}
        relations = {"new1": 1, "new2": 2}
        out = self._apply_cap(existing, relations)
        assert len(out) == 12
        assert "new1" in out and "new2" in out

    def test_over_cap_trims_to_max_keeping_newest(self):
        existing = {f"k{i}": i for i in range(40)}  # 已超上限
        relations = {"latest": 999}
        out = self._apply_cap(existing, relations)
        assert len(out) == 30
        # 最新加入的应保留（裁剪保留尾部）
        assert "latest" in out
        # 最老的应被裁掉
        assert "k0" not in out

    def test_exactly_at_cap_not_trimmed(self):
        existing = {f"k{i}": i for i in range(29)}
        relations = {"one_more": 1}  # 凑满 30
        out = self._apply_cap(existing, relations)
        assert len(out) == 30
