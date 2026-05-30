"""v0.9.6 Property 3: 压抑话题去重幂等。"""
import sys
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})

from anima.mixins.scars import ScarsMixin  # noqa: E402


class Host(ScarsMixin):
    def __init__(self, config):
        self.config = config
        self._topics = []

    def _read_suppressed_topics(self):
        import copy
        return copy.deepcopy(self._topics)

    def _write_suppressed_topics(self, t):
        self._topics = t


class TestSuppressDedup:
    def test_identical_not_added_twice(self):
        h = Host({"dedup_text_threshold": 0.7})
        h._add_suppressed_topic("想说但被忽略了：今天天气真好我想出去玩", "ignored")
        assert len(h._topics) == 1
        # 完全相同 → 不重复加
        h._add_suppressed_topic("想说但被忽略了：今天天气真好我想出去玩", "ignored")
        assert len(h._topics) == 1

    def test_near_duplicate_not_added(self):
        h = Host({"dedup_text_threshold": 0.6})
        h._add_suppressed_topic("我想跟他说说最近工作上的烦心事", "ignored")
        # 近义改写 → 高相似度 → 不加
        h._add_suppressed_topic("我想跟他聊聊最近工作上的烦心事情", "ignored")
        assert len(h._topics) == 1

    def test_unrelated_added(self):
        h = Host({"dedup_text_threshold": 0.7})
        h._add_suppressed_topic("我想跟他说说工作的事", "ignored")
        h._add_suppressed_topic("完全不相干的另一件事关于晚饭吃什么", "ignored")
        assert len(h._topics) == 2

    def test_resolved_topic_not_block(self):
        h = Host({"dedup_text_threshold": 0.7})
        h._topics = [{"topic": "已解决的旧话题内容", "resolved": True}]
        # 与已解决话题相似不应阻止新增（去重只看未解决的）
        h._add_suppressed_topic("已解决的旧话题内容", "ignored")
        # resolved 的会在写入时被过滤掉，新话题加入
        assert any(not t.get("resolved") for t in h._topics)
