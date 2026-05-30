"""v0.9.5 Property 5: 身份危机内生触发不依赖 Sylanne。"""
from datetime import datetime, timedelta

from hypothesis import given, settings, strategies as st

from _danger_host import DangerHost


class TestIdentityInternalTrigger:
    def test_disabled_no_change(self):
        h = DangerHost(config={"danger_identity_crisis": False})
        h._identity_stability = 1.0
        h._danger_identity_crisis_update("")
        assert h._identity_stability == 1.0

    def test_high_emotion_plus_identity_scar_drops(self):
        h = DangerHost(config={"danger_identity_crisis": True})
        h._identity_stability = 1.0
        h._state = {"last_emotion_score": 0.9}
        h._scars = {"identity_denial": {"sensitivity": 2.0}}
        h._danger_identity_crisis_update("")  # 无 Sylanne
        assert h._identity_stability < 1.0

    def test_recent_mutation_drops(self):
        h = DangerHost(config={"danger_identity_crisis": True})
        h._identity_stability = 1.0
        h._state = {"mutation_history": [{"timestamp": datetime.now().isoformat()}]}
        h._danger_identity_crisis_update("")
        assert h._identity_stability < 1.0

    def test_no_internal_signal_no_drop(self):
        h = DangerHost(config={"danger_identity_crisis": True})
        h._identity_stability = 1.0
        h._state = {"last_emotion_score": 0.2}  # 低情绪、无伤痕、无突变
        h._danger_identity_crisis_update("")
        assert h._identity_stability == 1.0

    def test_old_mutation_no_drop(self):
        h = DangerHost(config={"danger_identity_crisis": True})
        h._identity_stability = 1.0
        old = (datetime.now() - timedelta(days=5)).isoformat()
        h._state = {"mutation_history": [{"timestamp": old}]}
        h._danger_identity_crisis_update("")
        assert h._identity_stability == 1.0


@settings(max_examples=100)
@given(
    emotion=st.floats(min_value=0.0, max_value=1.0),
    has_id_scar=st.booleans(),
    mutated_recently=st.booleans(),
)
# Feature: danger-features-fidelity, Property 5: 身份危机内生触发不依赖 Sylanne ——
# 空 sylanne_state 下，当 (emotion>0.85 且 identity_denial 伤痕存在) 或 近48h有突变 时稳定度严格下降；
# 否则不因内生信号下降。
def test_prop5_internal_trigger(emotion, has_id_scar, mutated_recently):
    h = DangerHost(config={"danger_identity_crisis": True})
    h._identity_stability = 1.0
    state = {"last_emotion_score": emotion}
    if mutated_recently:
        state["mutation_history"] = [{"timestamp": datetime.now().isoformat()}]
    h._state = state
    h._scars = {"identity_denial": {"sensitivity": 1.5}} if has_id_scar else {}

    h._danger_identity_crisis_update("")

    should_drop = (emotion > 0.85 and has_id_scar) or mutated_recently
    if should_drop:
        assert h._identity_stability < 1.0
    else:
        assert h._identity_stability == 1.0
