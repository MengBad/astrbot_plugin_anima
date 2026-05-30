"""v0.9.10 schema 默认值冒烟测试。

验证 _conf_schema.json 中 capability-loop-strengthening 新增的 5 个配置项存在
且默认值正确。这是静态 schema 值的冒烟/示例测试（非 Hypothesis 属性测试），
每个 key 1-3 条断言。

_Requirements: 1.1, 1.2, 2.5, 3.1, 3.2, 3.3, 6.4, 7.2, 7.5
"""
import json
import os

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "_conf_schema.json")


def _load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestCapabilityPromoteEnabled:
    def test_exists_bool_default_false(self):
        item = _load_schema()["capability_promote_enabled"]
        assert item["type"] == "bool"
        assert item["default"] is False

    def test_hint_has_high_token_marker(self):
        # hint 标注 🔴 高 token，提示晋升出的命名工具会增加输入 token
        item = _load_schema()["capability_promote_enabled"]
        assert "🔴" in item.get("hint", "")


class TestCapabilityPromoteTopK:
    def test_exists_int_default_3(self):
        item = _load_schema()["capability_promote_top_k"]
        assert item["type"] == "int"
        assert item["default"] == 3


class TestCapabilityMatchHintEnabled:
    def test_exists_bool_default_true(self):
        item = _load_schema()["capability_match_hint_enabled"]
        assert item["type"] == "bool"
        assert item["default"] is True


class TestCapabilityMatchHintThreshold:
    def test_exists_float_default_0_2(self):
        item = _load_schema()["capability_match_hint_threshold"]
        assert item["type"] == "float"
        assert item["default"] == 0.2


class TestCapabilityMatchHintBackend:
    def test_exists_string_default_lexical(self):
        item = _load_schema()["capability_match_hint_backend"]
        assert item["type"] == "string"
        assert item["default"] == "lexical"

    def test_options_include_lexical_and_embedding(self):
        item = _load_schema()["capability_match_hint_backend"]
        options = item.get("options", [])
        assert "lexical" in options
        assert "embedding" in options
