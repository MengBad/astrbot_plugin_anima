"""v0.9.4 Property 6: 价值分不含自封置信度。"""
from datetime import datetime

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


@settings(max_examples=100)
@given(
    usage=st.integers(min_value=0, max_value=50),
    n_corr=st.integers(min_value=0, max_value=10),
    conf_a=st.floats(min_value=0.0, max_value=1.0),
    conf_b=st.floats(min_value=0.0, max_value=1.0),
)
# Feature: capability-system-closed-loop, Property 6: 价值分不含自封置信度 ——
# 两条能力若 usage/corrections/last_updated 相同而 confidence 不同，则价值分相等。
def test_prop6_value_score_ignores_confidence(usage, n_corr, conf_a, conf_b):
    host = CapHost()
    now = datetime.now()
    ts = now.isoformat()
    corr = [{"ts": ts} for _ in range(n_corr)]
    a = {"usage_count": usage, "corrections": list(corr), "last_updated": ts, "confidence": conf_a}
    b = {"usage_count": usage, "corrections": list(corr), "last_updated": ts, "confidence": conf_b}
    assert host._capability_value_score(a, now) == host._capability_value_score(b, now)
