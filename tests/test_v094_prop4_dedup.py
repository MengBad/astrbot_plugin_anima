"""v0.9.4 Property 4: 去重不误合并且同概念合并（泛化文本相似度）。"""
from hypothesis import given, settings, strategies as st

from anima.capability_dedup import find_similar_capability, text_similarity


# Feature: capability-system-closed-loop, Property 4: 去重不误合并且同概念合并 ——
# 既有"不相关 4 能力"样本仍判不合并；字符 2-gram Jaccard ≥ 阈值的一对判合并。
class TestProp4Dedup:
    def test_unrelated_still_kept_apart(self):
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
            assert find_similar_capability(name, desc, existing, text_threshold=0.6) == -1, \
                f"{name} 不应被误合并"

    def test_high_text_similarity_merges(self):
        """两个无核心语义槽位、但名称+描述高度相似的中文长名能力应被合并。"""
        existing = [{
            "name": "每日心情总结助手",
            "description": "把我今天的多条心情记录整理成一段温柔的总结",
        }]
        # 近乎同义改写
        idx = find_similar_capability(
            "每日心情总结小工具",
            "把我今天的多条心情记录整理成一段温柔的小结",
            existing,
            text_threshold=0.6,
        )
        assert idx == 0

    @settings(max_examples=100)
    @given(
        a=st.text(min_size=3, max_size=30),
        b=st.text(min_size=3, max_size=30),
    )
    def test_text_similarity_bounds(self, a, b):
        sim = text_similarity(a, b)
        assert 0.0 <= sim <= 1.0
        # 自相似度为 1（非空）
        assert abs(text_similarity(a, a) - 1.0) < 1e-9
