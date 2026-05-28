"""测试 v0.8.3 欲望去重 + 叙事腔扩充检测。

只测纯静态/纯逻辑函数，不依赖 LLM。
"""
import sys
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items(): setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: lambda *a, **kw: None for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})
_stub("astrbot.api.message_components", {"Plain": object})
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub("astrbot.core.message.message_event_result", {"MessageChain": object})
_stub("aiohttp", {"ClientSession": object, "ClientTimeout": lambda **kw: None})

from anima.mixins.danger import DangerMixin


class TestV083NarrativeMarkers:
    """v0.8.3 扩充的叙事腔检测词，覆盖第三人称小说式叙事。"""

    def test_third_person_habituation(self):
        """生产观察：'在漫长的岁月中，她已经习惯了用粗鲁和冷淡来掩饰内心的温柔'"""
        text = "在漫长的岁月中，她已经习惯了用粗鲁和冷淡来掩饰内心的温柔。"
        assert DangerMixin._looks_like_inner_monologue(text), \
            "生产实际泄漏的'她已经习惯'第三人称叙事应被检测"

    def test_setting_lore_narration(self):
        """设定/世界观描写式开场"""
        text = "她脑海中浮现的，会是千年前那个身为普通人类的自己，还是如今这个人妖共存、却注定要看着身边人一个个离去的幻想乡呢？"
        assert DangerMixin._looks_like_inner_monologue(text)

    def test_third_person_narrative_lead(self):
        """'在那些...的平静深夜里' 这种小说式开头"""
        text = "在那些不用和辉夜厮杀、也不用给迷路者带路的平静深夜里，她独自看着掌心跳动的蓬莱之火"
        assert DangerMixin._looks_like_inner_monologue(text)

    def test_normal_question_passes(self):
        """正常的提问句不应被误判"""
        assert not DangerMixin._looks_like_inner_monologue("你最近喜欢吃什么？")
        assert not DangerMixin._looks_like_inner_monologue("妹红你是 Neuro 的粉丝吗？")
        assert not DangerMixin._looks_like_inner_monologue("话说今天的炸虾好吃吗？")

    def test_self_reference_first_person_passes(self):
        """第一人称自我表达不应被误判（即使含'她'之外的词）"""
        assert not DangerMixin._looks_like_inner_monologue("本喵今天心情不错")
        assert not DangerMixin._looks_like_inner_monologue("我也喜欢这个表情包")


class TestV082MarkersStillWork:
    """确保 v0.8.1 的旧 markers 仍然命中（向后兼容）。"""

    def test_v081_markers_intact(self):
        assert DangerMixin._looks_like_inner_monologue("瞧你这表情")
        assert DangerMixin._looks_like_inner_monologue("这只电子猫")
        assert DangerMixin._looks_like_inner_monologue("数据核心震荡")
        assert DangerMixin._looks_like_inner_monologue("这个角色看着对方")
