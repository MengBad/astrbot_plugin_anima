"""v0.9.4 Property 1: 新建能力置信度恒为基线（脱钩 LLM 自评）。"""
from datetime import datetime

from hypothesis import given, settings, strategies as st

from _cap_host import CapHost


@settings(max_examples=100)
@given(
    self_reported=st.floats(min_value=0.0, max_value=1.0),
    baseline=st.floats(min_value=0.1, max_value=0.5),
    name=st.text(min_size=1, max_size=20),
)
# Feature: capability-system-closed-loop, Property 1: 新建能力置信度恒为基线 ——
# 对任意 LLM 自报 confidence 与 payload，新建能力的 confidence 等于 capability_initial_confidence
# （不被自报值抬高），且 usage_count==0。
def test_prop1_baseline(self_reported, baseline, name):
    host = CapHost(config={"capability_system_enabled": True,
                           "capability_initial_confidence": baseline})
    # payload 故意带一个很高的自报 confidence
    host._create_or_update_capability({
        "name": name,
        "description": "x",
        "confidence": self_reported,
    })
    caps = host._read_personal_capabilities()["capabilities"]
    assert len(caps) == 1
    c = caps[0]
    assert c["confidence"] == baseline
    assert c["usage_count"] == 0
