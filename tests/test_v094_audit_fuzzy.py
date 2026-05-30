"""v0.9.4 体检输出 + 模糊名解析 + 配置项存在性 示例测试。"""
import json
from pathlib import Path

from _cap_host import CapHost

ROOT = Path(__file__).resolve().parent.parent


class TestAudit:
    def test_empty_audit(self):
        host = CapHost(config={"capability_initial_confidence": 0.3})
        a = host._audit_capabilities()
        assert a["total"] == 0
        assert a["avg_conf"] == 0.0
        assert a["inflated"] == 0

    def test_audit_counts_inflated(self):
        caps = [
            {"name": "a", "usage_count": 0, "confidence": 0.9, "corrections": []},  # inflated
            {"name": "b", "usage_count": 0, "confidence": 0.3, "corrections": []},  # baseline, not inflated
            {"name": "c", "usage_count": 5, "confidence": 0.8, "corrections": [{}]},  # used, not zero_use
        ]
        host = CapHost(config={"capability_initial_confidence": 0.3}, caps=caps)
        a = host._audit_capabilities()
        assert a["total"] == 3
        assert a["zero_use"] == 2
        assert a["inflated"] == 1
        assert a["inflated_samples"] == ["a"]
        assert a["total_usage"] == 5
        assert a["total_corrections"] == 1


class TestFuzzyResolve:
    def _caps(self):
        return [
            {"name": "每日心情总结助手", "description": "x"},
            {"name": "WeatherFetcher", "description": "y"},
        ]

    def test_exact(self):
        host = CapHost(config={"capability_dedup_text_threshold": 0.6})
        c = host._resolve_capability("WeatherFetcher", self._caps())
        assert c["name"] == "WeatherFetcher"

    def test_case_insensitive_substring(self):
        host = CapHost(config={"capability_dedup_text_threshold": 0.6})
        c = host._resolve_capability("weatherfetcher", self._caps())
        assert c["name"] == "WeatherFetcher"

    def test_partial_substring(self):
        host = CapHost(config={"capability_dedup_text_threshold": 0.6})
        c = host._resolve_capability("心情总结", self._caps())
        assert c["name"] == "每日心情总结助手"

    def test_no_match_returns_none(self):
        host = CapHost(config={"capability_dedup_text_threshold": 0.6})
        assert host._resolve_capability("完全不相干的东西xyz", self._caps()) is None

    def test_empty(self):
        host = CapHost(config={})
        assert host._resolve_capability("", self._caps()) is None
        assert host._resolve_capability("x", []) is None


class TestConfigSchema:
    def test_new_config_keys_exist(self):
        with open(ROOT / "_conf_schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        for k, default in [
            ("capability_initial_confidence", 0.3),
            ("capability_unused_decay_days", 14),
            ("capability_unused_drop_days", 30),
            ("capability_max_total", 40),
            ("capability_dedup_text_threshold", 0.6),
        ]:
            assert k in schema, f"缺少配置项 {k}"
            assert schema[k]["default"] == default
