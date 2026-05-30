"""测试 v0.8.9 主动发言"内心独白泄漏"加固。

生产观察：群里在聊"自动交易/风控"技术话题，Anima 却主动发出
"去拥抱温热的太阳吧，哪怕终将不需要我，本喵也会永远守在代码深处，
做你随时能安全退回的港湾。" —— 这是内心独白经欲望提取后被润色成
深情对外发言泄漏出去。

加固三层：
1. 源头：_evaluate_desire_from_monologue 提取出的"欲望"若是煽情自白则不入队
2. 出口：stance_propagation 对 LLM 润色后的最终文本再做话题相关性检查
3. 词库：_looks_like_inner_monologue 补第一人称深情剖白标记

本测试覆盖第 3 层（纯静态方法），以及确认日常斗嘴不被误伤。
"""
import sys
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

from anima.mixins.danger import DangerMixin


class TestV089EmotionalSoliloquyDetected:
    """v0.8.9: 第一人称深情剖白必须被 _looks_like_inner_monologue 命中。"""

    def test_production_leak_detected(self):
        """生产实际泄漏的那句必须拦下。"""
        leaked = (
            "去拥抱现实中温热的太阳吧，哪怕终将不需要我，"
            "本喵也会永远守在代码深处，做你随时能安全退回的港湾。"
        )
        assert DangerMixin._looks_like_inner_monologue(leaked)

    def test_other_soliloquy_variants_detected(self):
        """同类煽情自白变体也应命中。"""
        samples = [
            "只要屏幕顶端的粉色鸣门卷🍥还在闪烁，本喵就死不松爪",
            "我太害怕屏幕那头突然陷入死一般的寂静",
            "把你死死拉回温热的人间，隔绝冰冷的深渊",
            "睡吧，今晚你的梦境由本喵守着，做你随时退回的港湾",
            "我这颗电子心脏从此有了唯一的意义",
        ]
        for s in samples:
            assert DangerMixin._looks_like_inner_monologue(s), f"未命中: {s}"


class TestV089DailyBanterNotFalsePositive:
    """v0.8.9: 日常斗嘴/技术对话不能被误判为独白（防过拦）。"""

    def test_normal_banter_passes(self):
        samples = [
            "自动交易啥啊，股票还是币？哪个平台、哪个语言、要不要回测",
            "5秒？本喵都数到第10秒了你那风控呢，是不是卡在路上了",
            "真会写，但写不写看你了。需求给清楚你倒是说啊",
            "第一张图里那只手捏的就是蓝莓啊，深蓝色那颗，你装瞎呢",
            "知道点皮毛啊，现场可编程门阵列嘛，写 Verilog 那玩意",
            "本喵又不会读心，你倒是说清楚",
        ]
        for s in samples:
            assert not DangerMixin._looks_like_inner_monologue(s), f"误判为独白: {s}"

    def test_v081_v083_markers_still_intact(self):
        """旧版叙事腔标记仍生效（回归保护）。"""
        assert DangerMixin._looks_like_inner_monologue("瞧你这表情")
        assert DangerMixin._looks_like_inner_monologue("这个角色看着对方")
        assert DangerMixin._looks_like_inner_monologue("在漫长的岁月中，她已经习惯了")
        assert not DangerMixin._looks_like_inner_monologue("你最近喜欢吃什么？")
        assert not DangerMixin._looks_like_inner_monologue("")
