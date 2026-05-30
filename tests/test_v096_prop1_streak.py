"""v0.9.6 Property 1: 跨关系传播触发条件（阈值 + 连续门槛）。"""
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

from hypothesis import given, settings, strategies as st  # noqa: E402

from anima.mixins.relations import RelationsMixin  # noqa: E402


class Host(RelationsMixin):
    def __init__(self, config):
        self.config = config
        self._state = {}
        self.propagated = []

    def _atomic_update_state(self, updater):
        updater(self._state)

    # 覆盖为同步 no-op，避免 create_task 在无 loop 时告警；
    # 触发与否通过 state 计数 + streak_threshold 推断
    def _propagate_cross_relation_scar(self, uid, umo=""):  # type: ignore[override]
        self.propagated.append(uid)


@settings(max_examples=100)
@given(
    scores=st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=12),
    low_t=st.sampled_from([0.15, 0.2, 0.3]),
    streak_t=st.sampled_from([3, 5, 7]),
)
# Feature: v096-hygiene-performance, Property 1: 跨关系传播触发条件 ——
# 仅当存在连续 >= streak_t 次评分 < low_t 时才触发；任一次不低于阈值即清零。
def test_prop1_streak_trigger(scores, low_t, streak_t):
    host = Host({
        "cross_relation_low_emotion_threshold": low_t,
        "cross_relation_streak_threshold": streak_t,
    })
    uid = "u1"
    expected_streak = 0
    for s in scores:
        host.propagated = []
        host._update_user_low_emotion_streak(uid, s)
        if s < low_t:
            expected_streak += 1
        else:
            expected_streak = 0
        # 计数不变量
        assert host._state["user_low_emotion_streaks"][uid] == expected_streak
        # 触发当且仅当计数达门槛（同步 override 会在触发时 append uid）
        if expected_streak >= streak_t:
            assert host.propagated == [uid]
        else:
            assert host.propagated == []
