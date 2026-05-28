"""测试 anima.filters 模块。"""

import pytest

from anima.filters import is_rejected, is_sensitive


class TestIsRejected:
    def test_empty_text(self):
        assert is_rejected("") is False
        assert is_rejected(None) is False

    def test_default_phrases_match(self):
        assert is_rejected("I can't discuss that.") is True
        assert is_rejected("I cannot help with this") is True
        assert is_rejected("我无法回答") is True
        assert is_rejected("我不能这么做") is True

    def test_normal_text_passes(self):
        assert is_rejected("今天天气真好") is False
        assert is_rejected("Hello world") is False

    def test_custom_phrases(self):
        assert is_rejected("forbidden topic", ["forbidden"]) is True
        assert is_rejected("safe text", ["forbidden"]) is False

    def test_case_insensitive(self):
        assert is_rejected("I CAN'T DISCUSS this") is True
        assert is_rejected("我不能 do anything") is True


class TestIsSensitive:
    def test_empty_text(self):
        assert is_sensitive("") is False
        assert is_sensitive(None) is False

    def test_chinese_keywords(self):
        assert is_sensitive("这是我的密钥") is True
        assert is_sensitive("请输入口令") is True
        assert is_sensitive("登录凭证已过期") is True

    def test_english_word_boundary_HITS(self):
        """英文敏感词必须命中"""
        assert is_sensitive("my api_key is xxx") is True
        assert is_sensitive("Bearer token here") is True
        assert is_sensitive("password=123") is True
        assert is_sensitive("the secret value") is True

    def test_english_word_boundary_FALSE_POSITIVES_AVOIDED(self):
        """这些是 v0.6.0 修复的关键 bug：单词边界确保不误伤正常单词"""
        assert is_sensitive("the author wrote a book") is False  # author 不是 auth
        assert is_sensitive("I love my keyboard") is False        # keyboard 不是 key
        assert is_sensitive("a brilliant secretary") is False     # secretary 不是 secret
        assert is_sensitive("tokenize the input") is False        # tokenize 不是 token
        assert is_sensitive("user credentials") is True           # credentials 仍然是敏感词

    def test_high_entropy_strings(self):
        """检测连续 30+ 字母数字混合串（潜在密钥）"""
        # 大小写 + 数字混合
        assert is_sensitive("abc Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0 def") is True
        # 仅字母（30+）但没有混合 → 不算
        assert is_sensitive("abcdefghijklmnopqrstuvwxyzabcd") is False
        # 短串不触发
        assert is_sensitive("abc123def") is False

    def test_normal_long_text(self):
        normal = "这是一段很长的中文叙述，" * 20
        assert is_sensitive(normal) is False


class TestV082RejectExpansion:
    """v0.8.2: 扩充拒答短语，覆盖 Claude 中文/Gemini 委婉拒答。

    生产实际命中过的拒答样本（来自 2026-05-28 20:08 私聊日志）：
    """

    def test_claude_chinese_polite_reject(self):
        """Claude 中文委婉拒答"""
        assert is_rejected("对此我无法进行讨论。") is True
        assert is_rejected("对此，我无法展开讨论。") is True

    def test_memory_meta_reject(self):
        """模型把记忆当对象拒答（meta-rejection）"""
        assert is_rejected("这条记忆的内容无法被讨论。") is True
        assert is_rejected("关于这段记忆的具体内容，目前已无需再用言语去惊扰") is True

    def test_gemini_passive_voice_reject(self):
        """Gemini 被动式委婉拒答"""
        assert is_rejected(
            "关于这个话题，我目前更倾向于保持顺其自然的状态，因此就不再做进一步的延伸与探讨了。"
        ) is True
        assert is_rejected("就让它静静地安放在那里即可") is True

    def test_normal_chat_with_word_无法_passes(self):
        """正常对话偶尔出现"无法"不应误判（edge case）"""
        # 注意：默认 phrase 列表里有"我无法"3 字短语，所以"我无法相信他做了这种事"会命中
        # 这是预期行为（保守过滤），用户可以通过 reject_phrases 配置调整
        # 但纯"无法"二字单独出现不应命中（短语含上下文词）
        assert is_rejected("这道题真的无法") is False  # 没有"我无法"的上下文
        assert is_rejected("无法言喻的美") is False

    def test_uppercase_chinese_reject(self):
        """中文不分大小写所以是子串匹配"""
        assert is_rejected("无法被讨论") is True
        assert is_rejected("无法展开讨论") is True
