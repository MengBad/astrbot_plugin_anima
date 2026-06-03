"""Anima 可读性：/anima_help 与 ui_labels 冒烟测试。"""
import json
import os
import sys
import types

# astrbot 桩（与 tests/_cap_host.py 约定一致）
def _stub(name, attrs=None):
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub("astrbot")
_stub("astrbot.api", {"logger": types.SimpleNamespace(info=print, debug=print, warning=print, error=print)})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})

from anima.ui_labels import render_help_text, label_stat_key, config_label  # noqa: E402


class TestAnimaHelp:
    def test_help_contains_all_sections(self):
        text = render_help_text()
        for section in ("日常查看", "运维 / 成本", "能力系统", "高级 / 管理"):
            assert section in text

    def test_help_lists_key_commands(self):
        text = render_help_text()
        assert "/anima_notes" in text
        assert "/anima_stats" in text
        assert "/anima_capabilities_audit" in text
        assert "/anima_scan_rejects" in text

    def test_help_differentiates_capability_commands(self):
        text = render_help_text()
        assert "autonomy" in text and "capabilities_audit" in text
        assert "概览" in text or "速览" in text
        assert "体检" in text

    def test_metric_labels(self):
        assert label_stat_key("llm.emotion") == "情绪评分"
        assert label_stat_key("stance.blocked.monologue") == "内心独白泄漏拦截"

    def test_config_friendly_names(self):
        assert config_label("dashboard_standalone_enabled") == "独立端口仪表盘"
        assert "插件配置" in config_label("unknown_key_xyz")


class TestConfSchemaCategories:
    SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "_conf_schema.json")

    def test_descriptions_have_category_prefix(self):
        with open(self.SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        tags = ("[核心]", "[模型]", "[可选模块]", "[仪表盘]", "[自主性]", "[能力系统]", "[高危]")
        for key, item in schema.items():
            desc = item.get("description", "")
            assert any(desc.startswith(t) for t in tags), f"{key} missing category prefix: {desc[:40]}"

    def test_dashboard_enabled_tagged(self):
        with open(self.SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        assert schema["dashboard_enabled"]["description"].startswith("[仪表盘]")
