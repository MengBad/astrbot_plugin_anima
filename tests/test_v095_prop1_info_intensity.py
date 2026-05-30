"""v0.9.5 Property 1: 主动信息收集 intensity 与开关一致。

_danger_active_info_collection 依赖较多（话题相关性、叙事腔等），这里用一个装好
全部依赖 stub 的宿主跑通它，断言写入欲望的 intensity 与 active_info_collection_can_speak 一致。
"""
import asyncio
import types

from _danger_host import DangerHost


class _Ev:
    def __init__(self, msg="今天天气不错我们聊聊吧"):
        self.message_str = msg
        self.unified_msg_origin = "umo_a"
        self.message_obj = types.SimpleNamespace(sender=types.SimpleNamespace(user_id="u1"))
    def get_sender_name(self):
        return "对方"


class _InfoHost(DangerHost):
    """补齐 _danger_active_info_collection 需要的依赖。"""
    def __init__(self, config):
        super().__init__(config)
        self.llm_text = "你今天心情怎么样呀"  # 合法提问，非叙事腔，<60 字

        host = self

        class _Ctx:
            async def llm_generate(self, chat_provider_id=None, prompt=None, **kw):
                return types.SimpleNamespace(completion_text=host.llm_text)
        self.context = _Ctx()

    async def _get_provider_id(self, event=None, prefer=""):
        return "prov1"

    def _is_rejected(self, text):
        return False

    def _looks_like_inner_monologue(self, text):
        return False

    def _build_recent_context_text(self, event):
        return getattr(event, "message_str", "")

    async def _is_topic_relevant_to_context(self, topic, ctx):
        return True  # 视为相关，不拦

    @staticmethod
    def _get_event_umo(event):
        return getattr(event, "unified_msg_origin", "") or ""


def _run(host):
    asyncio.run(host._danger_active_info_collection(_Ev(), "bot 的回复"))


# Feature: danger-features-fidelity, Property 1: 信息收集 intensity 与开关一致 ——
# can_speak=true → intensity>0.5（可越过 stance 门槛）；false → <=0.5（仅上下文）。
class TestInfoIntensity:
    def test_can_speak_true_above_threshold(self):
        h = _InfoHost(config={
            "danger_active_info_collection": True,
            "desire_enabled": True,
            "active_info_collection_can_speak": True,
            "desire_max_queue": 5,
        })
        _run(h)
        assert len(h._desires) == 1
        assert h._desires[0]["intensity"] > 0.5
        assert h._desires[0]["source"] == "info_collection"

    def test_can_speak_false_below_threshold(self):
        h = _InfoHost(config={
            "danger_active_info_collection": True,
            "desire_enabled": True,
            "active_info_collection_can_speak": False,
            "desire_max_queue": 5,
        })
        _run(h)
        assert len(h._desires) == 1
        assert h._desires[0]["intensity"] <= 0.5

    def test_stat_bump_recorded(self):
        h = _InfoHost(config={
            "danger_active_info_collection": True,
            "desire_enabled": True,
            "desire_max_queue": 5,
        })
        _run(h)
        assert h.stats.get("llm.info_collection") == 1

    def test_desire_disabled_warns_once_no_write(self):
        h = _InfoHost(config={
            "danger_active_info_collection": True,
            "desire_enabled": False,
        })
        _run(h)
        assert h._desires == []
        assert "danger_active_info_collection" in getattr(h, "_warned_desire_dep", set())
