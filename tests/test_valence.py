"""测试 anima.valence 模块。"""

import pytest

from anima.valence import estimate_memory_valence, rerank_memories_by_emotion


class TestValence:
    def test_empty(self):
        assert estimate_memory_valence("") == 0.0

    def test_warm_text_positive(self):
        v = estimate_memory_valence("今天好开心，我喜欢你")
        assert v > 0

    def test_conflict_text_negative(self):
        v = estimate_memory_valence("好难过，被讨厌了")
        assert v < 0

    def test_clamped_range(self):
        # 大量正向词不会突破上限
        v = estimate_memory_valence("开心 温暖 喜欢 爱 幸福 笑 好 甜 抱 永远")
        assert v <= 0.5
        # 大量负向词不会突破下限
        v = estimate_memory_valence("伤心 难过 离开 讨厌 滚 吵 骗 哭 恨 再见")
        assert v >= -0.5

    def test_neutral_text_zero(self):
        assert estimate_memory_valence("今天去图书馆借了本书") == 0.0


class TestRerank:
    def test_empty(self):
        assert rerank_memories_by_emotion([], 0.5) == []

    def test_single_memory_unchanged(self):
        mems = ["唯一记忆"]
        assert rerank_memories_by_emotion(mems, 0.5) == mems

    def test_high_emotion_warm_first(self):
        mems = [
            "好难过被骗了",       # 冲突
            "今天好开心爱你",     # 温暖
            "去吃饭了",           # 中性
        ]
        result = rerank_memories_by_emotion(mems, current_emotion=0.7)
        # 高情绪：温暖优先
        assert "开心" in result[0]
        assert "难过" in result[-1]

    def test_low_emotion_conflict_first(self):
        mems = [
            "今天好开心爱你",
            "好难过被骗了",
            "去吃饭了",
        ]
        result = rerank_memories_by_emotion(mems, current_emotion=0.2)
        # 低情绪：冲突优先
        assert "难过" in result[0]
        assert "开心" in result[-1]
