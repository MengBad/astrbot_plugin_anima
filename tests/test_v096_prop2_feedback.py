"""v0.9.6 Property 2: 反馈三段判定。"""
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

import asyncio  # noqa: E402
import time  # noqa: E402
from hypothesis import given, settings, strategies as st  # noqa: E402

from anima.mixins.feedback import FeedbackMixin  # noqa: E402


class _Ev:
    def __init__(self, umo="u", msg="some reply text"):
        self.unified_msg_origin = umo
        self.message_str = msg


class Host(FeedbackMixin):
    def __init__(self, config, sim):
        self.config = config
        self._sim = sim
        # 观察窗口：模拟最近 bot 发言
        self._outgoing_by_umo = {"u": (time.time(), "上一条机器人发言")}

    async def _embed_one(self, text):
        return None  # 强制走 Jaccard 路径，但我们直接覆盖相似度

    def _cosine_similarity(self, a, b):
        return self._sim

    def _text_token_set(self, text):
        return {text}

    def _jaccard_similarity(self, a, b):
        return self._sim


@settings(max_examples=100)
@given(
    sim=st.floats(min_value=0.0, max_value=1.0),
    acc_t=st.sampled_from([0.4, 0.45, 0.5]),
    ign_t=st.sampled_from([0.1, 0.15, 0.2]),
)
# Feature: v096-hygiene-performance, Property 2: 反馈三段判定 ——
# 无否定词时：accepted 当且仅当 sim>=acc_t；ignored 当且仅当 sim<ign_t；其余 none。
def test_prop2_three_way(sim, acc_t, ign_t):
    if ign_t >= acc_t:
        return  # 无意义组合
    host = Host({
        "feedback_accepted_threshold": acc_t,
        "feedback_ignored_threshold": ign_t,
    }, sim)
    # message_str 不含否定词
    result = asyncio.run(host._evaluate_feedback(_Ev(msg="嗯我觉得挺好的继续说")))
    if sim >= acc_t:
        assert result == "accepted"
    elif sim < ign_t:
        assert result == "ignored"
    else:
        assert result == "none"


def test_rejected_words_take_priority():
    host = Host({"feedback_accepted_threshold": 0.45, "feedback_ignored_threshold": 0.15}, 0.99)
    # 含否定词 → 无视相似度判 rejected
    result = asyncio.run(host._evaluate_feedback(_Ev(msg="不对，错了")))
    assert result == "rejected"
