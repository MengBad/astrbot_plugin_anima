"""v0.9.2 配置项存在性测试。

验证 _conf_schema.json 中存在 sediment_merge_llm_calls 且默认 false。
_Requirements: 8.1, 9.1_
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_schema():
    with open(ROOT / "_conf_schema.json", encoding="utf-8") as f:
        return json.load(f)


class TestMergeFlagConfig:
    def test_flag_exists(self):
        schema = _load_schema()
        assert "sediment_merge_llm_calls" in schema

    def test_flag_is_bool_default_false(self):
        schema = _load_schema()
        item = schema["sediment_merge_llm_calls"]
        assert item["type"] == "bool"
        assert item["default"] is False

    def test_flag_has_hint(self):
        schema = _load_schema()
        item = schema["sediment_merge_llm_calls"]
        # hint 提到合并统计计数项，方便用户在仪表盘核对
        assert "llm.sediment_merged" in item.get("hint", "")
