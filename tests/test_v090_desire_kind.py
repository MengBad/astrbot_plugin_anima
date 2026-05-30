"""测试 v0.9.0 欲望双类型隔离（inward / outward）。

根治长期顽疾：内心独白经欲望提取后被润色成深情对外发言泄漏。
从数据模型上隔离 —— inward 欲望永不进入 stance_propagation。
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


class TestDesireKindClassification:
    def test_outward_sources(self):
        for src in ("info_collection", "relationship", "memory_infection"):
            assert DesireMixin._desire_kind(src) == "outward", src

    def test_inward_sources(self):
        for src in ("self", "mutation", "capability_gap_rumination"):
            assert DesireMixin._desire_kind(src) == "inward", src

    def test_unknown_source_defaults_inward(self):
        """未知 source 保守归为 inward（不主动外发）。"""
        assert DesireMixin._desire_kind("something_new") == "inward"
        assert DesireMixin._desire_kind("") == "inward"


class TestDesireIsOutward:
    def test_explicit_kind_takes_priority(self):
        # 显式 kind 优先于 source 推断
        assert DesireMixin._desire_is_outward({"kind": "outward", "source": "self"})
        assert not DesireMixin._desire_is_outward({"kind": "inward", "source": "relationship"})

    def test_legacy_no_kind_falls_back_to_source(self):
        """旧数据无 kind 字段，按 source 推断（向后兼容）。"""
        assert DesireMixin._desire_is_outward({"source": "relationship"})
        assert DesireMixin._desire_is_outward({"source": "info_collection"})
        assert not DesireMixin._desire_is_outward({"source": "self"})
        assert not DesireMixin._desire_is_outward({"source": "mutation"})

    def test_legacy_no_kind_no_source_defaults_inward(self):
        """既无 kind 又无 source 的最老数据，保守不外发。"""
        assert not DesireMixin._desire_is_outward({"content": "旧执念"})

    def test_invalid_kind_falls_back_to_source(self):
        """kind 字段值非法时回退 source 推断。"""
        assert DesireMixin._desire_is_outward({"kind": "garbage", "source": "relationship"})
        assert not DesireMixin._desire_is_outward({"kind": "garbage", "source": "self"})


class TestStanceOnlyOutward:
    """模拟 stance_propagation 的筛选逻辑：inward 欲望必须被排除。"""

    @staticmethod
    def _eligible(desires):
        return [
            d for d in desires
            if d.get("intensity", 0) > 0.5
            and not d.get("satisfied", False)
            and DesireMixin._desire_is_outward(d)
        ]

    def test_inward_high_intensity_excluded(self):
        """高强度 inward 欲望（如突变执念 0.92）不能进入主动发言候选。"""
        desires = [
            {"id": "1", "intensity": 0.92, "source": "mutation", "kind": "inward",
             "content": "[突变执念] 守护你到永远"},
            {"id": "2", "intensity": 0.6, "source": "self", "kind": "inward",
             "content": "去拥抱温热的太阳吧，做你随时退回的港湾"},
        ]
        assert self._eligible(desires) == []

    def test_outward_eligible(self):
        desires = [
            {"id": "1", "intensity": 0.7, "source": "relationship", "kind": "outward",
             "content": "想问妹红是不是粉丝"},
        ]
        out = self._eligible(desires)
        assert len(out) == 1 and out[0]["id"] == "1"

    def test_mixed_only_outward_survives(self):
        desires = [
            {"id": "in", "intensity": 0.9, "source": "self", "kind": "inward", "content": "深情自白"},
            {"id": "out", "intensity": 0.7, "source": "info_collection", "kind": "outward", "content": "想问个问题"},
        ]
        out = self._eligible(desires)
        assert [d["id"] for d in out] == ["out"]
