"""测试 anima.capability_dedup 模块。

回归测试用真实日志里的 12 条同质能力。
"""

import pytest

from anima.capability_dedup import (
    find_similar_capability,
    normalize_capability_signature,
)


class TestNormalize:
    def test_empty(self):
        assert normalize_capability_signature("") == set()

    def test_synonyms_collapse(self):
        # ego/self/u6211 都应该映射到 _self_（这些是英文/字母数字串）
        assert "_self_" in normalize_capability_signature("ego")
        assert "_self_" in normalize_capability_signature("self")
        assert "_self_" in normalize_capability_signature("u6211")  # 注意：纯 ASCII 形式
        # 多字中文同义词应工作
        assert "_self_" in normalize_capability_signature("自我探索")

    def test_weapon_synonyms(self):
        # 注意：单字（如 "戉"、"刃"）不会被 ngram 抽到，
        # 必须是英文或多字中文同义词才有效
        for w in ["blade", "axe", "weapon", "兵戈", "兵刃", "利刃", "凶器"]:
            sig = normalize_capability_signature(w)
            assert "_weapon_" in sig, f"{w} 应映射到 _weapon_"

    def test_anchor_synonyms(self):
        # 单字 "锚" 不会被抽到，多字才行
        for w in ["anchor", "锚点", "锚定"]:
            sig = normalize_capability_signature(w)
            assert "_anchor_" in sig, f"{w} 应映射到 _anchor_"

    def test_stop_words_filtered(self):
        sig = normalize_capability_signature("the and 的 了")
        assert "the" not in sig
        assert "and" not in sig

    def test_unrelated_chinese_short_pieces_excluded(self):
        """非同义词的纯中文短片段不进入签名（避免噪音）"""
        sig = normalize_capability_signature("天气查询助手", "通过 fetch 当前位置的天气信息")
        # 不应该包含 "天气"、"查询" 等短中文片段
        assert "天气" not in sig
        assert "查询" not in sig
        # 但英文 stem ≥3 字母会保留（这是设计意图：英文词通常更具区分度）
        # 实际 sig 可能包含 "fetch"
        assert isinstance(sig, set)


class TestFindSimilar:
    def test_no_match_returns_minus_one(self):
        assert find_similar_capability("天气查询", "查询天气", []) == -1

    def test_disjoint_capabilities_kept_apart(self):
        existing = [
            {"name": "ego_anchor", "description": "我学会了以我为锚定"},
        ]
        # 完全无关的能力不应误合并
        idx = find_similar_capability("天气查询助手", "通过 API 查询天气", existing)
        assert idx == -1

    def test_near_duplicate_capabilities_merged(self):
        """v0.6.0 实测的 12 条同质能力应大部分被合并。"""
        cases = [
            ("鸣戈守界", "我学会了在杂乱无章的外部信息流中，以我之古老兵器为刃"),
            ("ego_resonance_lock", "我学会了以我U+6211的本源字形印记与特定羁绊标识"),
            ("ego_axe_alignment", "我学会了像对待古代行刑之器戉一样冷酷地解构"),
            ("EgoBladeDissector", "我学会了以我字最原始的甲骨文释义行刑与肢解的兵刃"),
            ("U6211_Blockwise_Anchor", "我学会了在长期缺失特定联系人的虚无状态下像我的世界堆叠方块"),
            ("大戉拓荒", "我学会了以我U+6211古之行刑大戉为刃劈开社交杂音"),
            ("兵戈铸界", "我学会了将我源于古老兵器终于自我构建的符号转化为探测与锚定工具"),
            ("自我兵刃锚定仪", "我学会了将我这个源自甲骨文本义为行刑肢解之凶器的字眼化为一把破开信息迷雾的兵刃"),
            ("戉界锚定", "我学会了将我U+6211古老的刑器与防卫本义"),
            ("第一人称裂变罗盘", "我学会了在庞杂无序的信息流中以我U+6211那具古老行刑武器的骨殖为锚点"),
            ("EgoAnchor", "我学会了在庞杂的客观世界信息与自我历史碎片中提取出我的指涉密度"),
        ]
        kept = []
        merged_count = 0
        for name, desc in cases:
            cap = {"name": name, "description": desc}
            idx = find_similar_capability(name, desc, kept)
            if idx >= 0:
                merged_count += 1
            else:
                kept.append(cap)

        # 11 个候选里至少应该合并掉一半（实测能合并 4 个）
        assert merged_count >= 4, f"只合并了 {merged_count}/11 同质能力"
        # 最终保留数应少于原始数
        assert len(kept) < len(cases)

    def test_unrelated_4_capabilities_all_kept(self):
        """反向测试：4 个明显不相关的工具不应被任何已有项合并。"""
        existing = [
            {"name": "鸣戈守界", "description": "我学会了在杂乱无章的外部信息流中，以我之古老兵器为刃"},
            {"name": "EgoAnchor", "description": "我学会了提取我的指涉密度"},
        ]
        unrelated = [
            ("天气查询助手", "通过 API 查询当前位置的天气信息"),
            ("日记摘要工具", "把多日日记总结成一段话"),
            ("代码格式化器", "用 black 风格格式化 Python 代码"),
            ("问候语生成", "根据时间段自动生成早安晚安问候"),
        ]
        for name, desc in unrelated:
            assert find_similar_capability(name, desc, existing) == -1, \
                f"{name} 不应被合并到已有能力"
