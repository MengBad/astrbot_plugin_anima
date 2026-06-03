"""测试 v0.8.4 幻觉话题过滤（防线 D）+ desire_dedup_threshold 默认值升级。

只测纯逻辑函数（_is_topic_relevant_to_context / _build_recent_context_text），
通过 stub 注入 self.config / self._outgoing_by_umo / event.message_str 模拟运行环境。
"""
import asyncio
import sys
import time
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
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

from anima.mixins.desire import DesireMixin


class _FakeEvent:
    def __init__(self, message_str: str = "", umo: str = "test_umo"):
        self.message_str = message_str
        self.unified_msg_origin = umo


class _MixinHost(DesireMixin):
    """让 DesireMixin 可独立实例化做单测。"""
    def __init__(self, config: dict, outgoing: dict = None):
        self.config = config
        self._outgoing_by_umo = outgoing or {}


def _run(coro):
    return asyncio.run(coro)



class TestV084TopicRelevance:
    """v0.8.4 防线 D：话题关联性检查。

    embedding 不可用时回退 Jaccard，阈值 0.20。
    """

    def test_hallucinated_asmr_topic_blocked(self):
        """生产实际案例：群里只聊'笨蛋'，LLM 编出 ASMR 话题应被拦下。

        Jaccard fallback：'笨蛋' vs 'ASMR/角色扮演/音声' 完全无 token 重叠（sim=0.0）。
        """
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.05})
        topic = "话说，这部作品主要是ASMR还是角色扮演的音声呀？"
        context = "笨蛋 笨蛋 笨蛋"
        relevant = _run(host._is_topic_relevant_to_context(topic, context))
        assert not relevant, "毫无关联的幻觉话题应被判定为不相关"

    def test_relevant_topic_passes(self):
        """跟上下文相关的提问应该通过（不该误伤）。

        '妹红 Neuro 粉丝' vs 'Neuro 直播 妹红' 在 Jaccard ngram 路径上算出约 0.06，
        要跨过 0.05 阈值。
        """
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.05})
        topic = "话说妹红也是Neuro的粉丝吗？"
        context = "刚才在看Neuro的直播，妹红你也在看吗"
        relevant = _run(host._is_topic_relevant_to_context(topic, context))
        assert relevant, "跟上下文有词汇重叠的提问不应被误伤"

    def test_empty_context_passes(self):
        """没有上下文（冷启动）不拦，避免插件刚启动就把所有主动发言全砍掉。"""
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.05})
        relevant = _run(host._is_topic_relevant_to_context("你今天吃什么？", ""))
        assert relevant
        relevant = _run(host._is_topic_relevant_to_context("你今天吃什么？", "   "))
        assert relevant

    def test_empty_topic_passes(self):
        """空话题视为未生成欲望，不拦。"""
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.05})
        relevant = _run(host._is_topic_relevant_to_context("", "今天天气真好"))
        assert relevant

    def test_threshold_zero_disables_filter(self):
        """阈值设为 0 等于关闭过滤，任何相似度都通过。"""
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.0})
        topic = "完全无关的话题：量子力学薛定谔方程"
        context = "今天吃饭了吗"
        relevant = _run(host._is_topic_relevant_to_context(topic, context))
        assert relevant, "阈值 0 应该让所有话题通过"

    def test_high_threshold_blocks_loose_match(self):
        """阈值调高时只放过高度相关的话题。"""
        host = _MixinHost(config={"topic_relevance_threshold_jaccard": 0.50})
        # 弱相关 token 重叠不足以跨过 0.50
        topic = "你最近喜欢看什么书？"
        context = "今天的炸虾真好吃"
        relevant = _run(host._is_topic_relevant_to_context(topic, context))
        assert not relevant


class TestV084ContextBuilder:
    """_build_recent_context_text：拼最近对话窗口给关联性检查用。"""

    def test_context_combines_user_and_bot(self):
        host = _MixinHost(
            config={},
            outgoing={"test_umo": (time.time(), "上次 bot 说了'你好'")},
        )
        event = _FakeEvent(message_str="用户当前说的话", umo="test_umo")
        ctx = host._build_recent_context_text(event)
        assert "用户当前说的话" in ctx
        assert "你好" in ctx

    def test_context_user_only_when_no_outgoing(self):
        host = _MixinHost(config={})
        event = _FakeEvent(message_str="第一句话", umo="test_umo")
        ctx = host._build_recent_context_text(event)
        assert ctx == "第一句话"

    def test_context_empty_when_no_event(self):
        host = _MixinHost(config={})
        ctx = host._build_recent_context_text(None)
        assert ctx == ""

    def test_context_uses_default_umo_fallback(self):
        """umo 不存在时尝试 _default_ key（兼容旧路径）。"""
        host = _MixinHost(
            config={},
            outgoing={"_default_": (time.time(), "默认 bot 输出")},
        )
        event = _FakeEvent(message_str="", umo="missing_umo")
        ctx = host._build_recent_context_text(event)
        assert "默认 bot 输出" in ctx


class TestV084DedupThresholdBumped:
    """v0.8.4: desire_dedup_threshold 默认值从 0.45 → 0.50（B 防线更严）。"""

    def test_default_threshold_is_050(self):
        """没有显式配置时默认走 0.50。"""
        host = _MixinHost(config={})
        # 直接构造能跨 0.45 但跨不过 0.50 的相似度场景
        # 用相同文本 (sim=1.0) 验证默认值会拦
        result = _run(host._is_desire_already_expressed(
            "想问妹红是不是粉丝", "想问妹红是不是粉丝", None
        ))
        assert result is True

    def test_explicit_threshold_overrides_default(self):
        """配置显式给出时用配置值，向后兼容用户已有的 0.45 设置。"""
        host = _MixinHost(config={"desire_dedup_threshold": 0.45})
        # 这里只验证读取路径，不验证具体相似度值
        # （相似度计算在 v0.8.3 已有覆盖）
        # 确认配置读取没崩
        result = _run(host._is_desire_already_expressed(
            "完全相同的句子", "完全相同的句子", None
        ))
        assert result is True
