"""测试 anima.similarity 模块。"""

import math

import pytest

from anima.similarity import (
    cosine_similarity,
    jaccard_similarity,
    text_jaccard,
    text_token_set,
)


class TestTextTokenSet:
    def test_empty(self):
        assert text_token_set("") == set()

    def test_english_only(self):
        s = text_token_set("hello world")
        assert "hello" in s
        assert "world" in s

    def test_short_english_excluded(self):
        s = text_token_set("a b cd")
        assert "a" not in s
        assert "cd" not in s  # < 3 字母不算

    def test_chinese_ngram(self):
        s = text_token_set("我喜欢你")
        # 应该有 2-字与 3-字 ngram
        assert "我喜" in s
        assert "喜欢" in s
        assert "欢你" in s
        assert "我喜欢" in s
        assert "喜欢你" in s

    def test_mixed_zh_en(self):
        s = text_token_set("hello 世界")
        assert "hello" in s
        assert "世界" in s

    def test_case_insensitive(self):
        s = text_token_set("Hello WORLD")
        assert "hello" in s
        assert "world" in s


class TestJaccard:
    def test_empty(self):
        assert jaccard_similarity(set(), set()) == 0.0
        assert jaccard_similarity(set(), {"a"}) == 0.0

    def test_identical(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial(self):
        # |交| = 1, |并| = 3 → 1/3
        sim = jaccard_similarity({"a", "b"}, {"a", "c"})
        assert abs(sim - 1 / 3) < 1e-9


class TestTextJaccard:
    def test_identical_texts(self):
        assert text_jaccard("我喜欢你", "我喜欢你") == 1.0

    def test_different_topics(self):
        sim = text_jaccard("今天天气真好", "学习数据结构")
        assert sim < 0.1

    def test_paraphrase_partial(self):
        """复述类应有可观察的相似度（ngram 重叠特性使 0.2-0.3 已是高重叠）"""
        sim = text_jaccard("我今天去吃饭了", "今天我去吃饭")
        assert sim > 0.2  # ngram tokenize 下相似但不会很高


class TestCosine:
    def test_empty(self):
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([1.0], []) == 0.0

    def test_length_mismatch(self):
        assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0

    def test_identical_vectors(self):
        assert abs(cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) - 1.0) < 1e-9

    def test_orthogonal(self):
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite(self):
        assert abs(cosine_similarity([1.0, 1.0], [-1.0, -1.0]) - (-1.0)) < 1e-9

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
