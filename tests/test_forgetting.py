"""测试 anima.forgetting 模块。"""

from datetime import datetime, timedelta

import pytest

from anima.forgetting import apply_forgetting


class TestApplyForgetting:
    def test_empty(self):
        assert apply_forgetting("", 14) == ""

    def test_no_timestamp_unchanged(self):
        notes = "我是一段没有时间戳的笔记"
        assert apply_forgetting(notes, 14) == notes

    def test_recent_unchanged(self):
        now = datetime(2026, 1, 1, 12, 0)
        recent_ts = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        notes = f"[{recent_ts}] 这是 5 天前的记忆"
        result = apply_forgetting(notes, halflife_days=14, now=now)
        # 5 天 < 14 天半衰期，不应该有模糊标记
        assert "模糊" not in result

    def test_past_halflife_marks_blurry(self):
        now = datetime(2026, 1, 1, 12, 0)
        old_ts = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
        notes = f"[{old_ts}] 这是 30 天前的记忆"
        result = apply_forgetting(notes, halflife_days=14, now=now)
        # 30 > 14 但 < 42，标 (记忆模糊)
        assert "(记忆模糊)" in result
        assert "极度模糊" not in result

    def test_far_past_marks_extreme_blur(self):
        now = datetime(2026, 1, 1, 12, 0)
        very_old = (now - timedelta(days=60)).strftime("%Y-%m-%d %H:%M")
        notes = f"[{very_old}] 这是 60 天前的记忆"
        result = apply_forgetting(notes, halflife_days=14, now=now)
        # 60 > 42 (= 14*3)，标 (记忆极度模糊)
        assert "极度模糊" in result

    def test_multiple_blocks_independently_aged(self):
        now = datetime(2026, 1, 1, 12, 0)
        recent = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        old = (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M")
        notes = f"[{recent}] 新记忆\n---\n[{old}] 旧记忆"
        result = apply_forgetting(notes, halflife_days=14, now=now)
        blocks = result.split("\n---\n")
        assert len(blocks) == 2
        assert "模糊" not in blocks[0]  # 新记忆不模糊
        assert "(记忆模糊)" in blocks[1]  # 旧记忆模糊

    def test_invalid_timestamp_block_kept(self):
        """格式不正确的时间戳不应崩溃。"""
        notes = "[invalid timestamp] 一些内容"
        result = apply_forgetting(notes, 14)
        assert result == notes  # 保持原样
