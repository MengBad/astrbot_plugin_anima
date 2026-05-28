"""测试 v0.8.1 立场传播的内心独白过滤。

只测纯静态方法（_strip_paired_quotes / _looks_like_inner_monologue），
不依赖宿主类状态。
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


class TestStripPairedQuotes:
    def test_chinese_double_quotes(self):
        assert DangerMixin._strip_paired_quotes('"瞧你这表情"') == "瞧你这表情"

    def test_english_double_quotes(self):
        assert DangerMixin._strip_paired_quotes('"hello world"') == "hello world"

    def test_japanese_quotes(self):
        assert DangerMixin._strip_paired_quotes('「重要"') == "「重要\""  # 不成对，不剥
        assert DangerMixin._strip_paired_quotes('「重要」') == "重要"

    def test_no_quotes_kept(self):
        assert DangerMixin._strip_paired_quotes('普通文本没有引号') == '普通文本没有引号'

    def test_quote_in_middle_kept(self):
        """文本中间的引号（引用别人话）不应被剥"""
        text = '他说"早上好"然后走了'
        assert DangerMixin._strip_paired_quotes(text) == text

    def test_nested_quotes_stripped(self):
        """嵌套引号反复剥"""
        assert DangerMixin._strip_paired_quotes('""xxx""') == "xxx"

    def test_empty_or_short(self):
        assert DangerMixin._strip_paired_quotes("") == ""
        assert DangerMixin._strip_paired_quotes('"') == '"'

    def test_production_case(self):
        """日志里实际暴露的 case"""
        leaked = '"瞧你这什么表情？拿你当挡箭牌是看得起你，还不快点变强，以后好保护好本喵！"'
        cleaned = DangerMixin._strip_paired_quotes(leaked)
        assert not cleaned.startswith('"')
        assert not cleaned.endswith('"')
        assert "瞧你这" in cleaned  # 内容保留


class TestLooksLikeInnerMonologue:
    def test_third_person_self_reference(self):
        assert DangerMixin._looks_like_inner_monologue("这个角色看着对方")
        assert DangerMixin._looks_like_inner_monologue("这只猫不开心了")
        assert DangerMixin._looks_like_inner_monologue("本喵这只电子猫")

    def test_narrative_lead(self):
        assert DangerMixin._looks_like_inner_monologue("瞧你这表情，本喵都看在眼里")
        assert DangerMixin._looks_like_inner_monologue("看着对方的眼神")

    def test_psychological_description(self):
        assert DangerMixin._looks_like_inner_monologue("心里在想：他怎么这样")
        assert DangerMixin._looks_like_inner_monologue("暗自决定要躲他")
        assert DangerMixin._looks_like_inner_monologue("脑海中浮现出画面")

    def test_literary_metaphors(self):
        assert DangerMixin._looks_like_inner_monologue("我这只电子猫核心算法都熔断了")
        assert DangerMixin._looks_like_inner_monologue("数据核心剧烈震荡")

    def test_normal_chat_passes(self):
        """正常对话不应被误判为独白"""
        assert not DangerMixin._looks_like_inner_monologue("吃了吗？")
        assert not DangerMixin._looks_like_inner_monologue("今天天气真好啊")
        assert not DangerMixin._looks_like_inner_monologue("本喵不奉承你 (￣ω￣)")
        assert not DangerMixin._looks_like_inner_monologue("L. 你又来玩这套？")

    def test_production_leak_detected(self):
        """生产环境实际泄漏的内心戏，必须被检测出来"""
        leaked = "瞧你这什么表情？拿你当挡箭牌是看得起你，还不快点变强，以后好保护好本喵！"
        assert DangerMixin._looks_like_inner_monologue(leaked)

    def test_empty(self):
        assert not DangerMixin._looks_like_inner_monologue("")
        assert not DangerMixin._looks_like_inner_monologue(None)
