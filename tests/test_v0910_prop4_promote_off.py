# Feature: capability-loop-strengthening, Property 4: 晋升默认关无回归 —— promote 关时零新注册
"""v0.9.10 Layer 1 属性测试 —— Property 4：晋升默认关无回归。

被测编排器：CapabilitiesMixin._refresh_capability_tool_belt（经下方 PromoteOffHost）。
配合真实纯函数 _select_promotion_set / _capability_value_score（均不被覆盖）。

属性：对任意能力集合，当 `capability_promote_enabled=false` 时，调用
`_refresh_capability_tool_belt` 因晋升而新注册的 Named_Tool 数为 0
（注册行为退化为 v0.9.4 既有逻辑，零回归）。

测试手法：子类化 tests/_cap_host.CapHost，注入会"真实新注册"语义的假注册函数
（append 到 self.registered 且 self._daily_tool_register["count"] += 1，使编排器
的前后差值逻辑在被调用时一定会判定为一次真实新注册）。因此若 gate 失效、注册被
错误地触发，本测试会立即捕获到 `registered` 非空与 `capability.promoted` 被累加。
gate 正常时则两者恒为空/0。

Validates: Requirements 2.1, 6.3
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from _cap_host import CapHost


class PromoteOffHost(CapHost):
    """最小宿主：注入会"真实新注册"的假注册函数 + 埋点计数。

    - _daily_tool_register / _promoted_cap_ids：编排器前后差值逻辑与 Trial_Slot
      判定所需的进程内状态。
    - _dynamically_register_capability_as_tool：被调用即视为一次真实新注册
      （记录 + count += 1）——故 promote 关时它绝不该被调用。
    - _stat_bump：把累加记入 self.stat_counts，便于断言 capability.promoted 从未被 bump。
    - _select_promotion_set / _refresh_capability_tool_belt：来自 mixin 的真实方法，不覆盖。
    """

    def __init__(self, config=None, caps=None):
        super().__init__(config=config, caps=caps)
        self._daily_tool_register = {"date": "", "count": 0}
        self._promoted_cap_ids = set()
        self.registered = []          # 任何一次注册都会被记录（promote 关时应为空）
        self.stat_counts = {}         # _stat_bump 记录

    def _stat_bump(self, key, n=1):
        self.stat_counts[key] = self.stat_counts.get(key, 0) + n

    def _dynamically_register_capability_as_tool(self, capability, force=False):
        # 任何调用都视为真实新注册：记录并增量计数。
        # 编排器据前后差值判定真实新注册 → 若被调用，capability.promoted 必被累加。
        self.registered.append(capability.get("id"))
        self._daily_tool_register["count"] = self._daily_tool_register.get("count", 0) + 1


@st.composite
def caps_scenario(draw):
    """随机能力列表（唯一 id、varied usage/corrections/last_updated）+ 随机 K(1..5)。"""
    n = draw(st.integers(min_value=0, max_value=12))
    caps = []
    for i in range(n):
        caps.append({
            "id": f"cap_{i}",
            "name": f"cap_{i}",
            "description": f"desc_{i}",
            "usage_count": draw(st.integers(min_value=0, max_value=50)),
            "corrections": ["c"] * draw(st.integers(min_value=0, max_value=5)),
            "last_updated": draw(st.sampled_from([
                "2024-01-01T00:00:00", "2025-01-01T00:00:00",
                "2023-06-15T12:00:00", "not-a-date", "",
            ])),
        })
    k = draw(st.integers(min_value=1, max_value=5))
    return caps, k


@settings(max_examples=100)
@given(caps_scenario())
def test_prop4_promote_off_no_registration(scenario):
    caps, k = scenario

    config = {
        "capability_promote_enabled": False,   # 关键：晋升默认关
        "capability_system_enabled": True,
        "capability_promote_top_k": k,
    }
    host = PromoteOffHost(config=config, caps=caps)

    host._refresh_capability_tool_belt()

    # 不变量 1：promote 关 → 零新注册（行为退化为 v0.9.4）。
    assert host.registered == [], (
        f"promote 关时不应有任何晋升注册，但 registered={host.registered}"
    )
    # 不变量 2：promote 关 → capability.promoted 埋点从未被累加。
    assert host.stat_counts.get("capability.promoted", 0) == 0, (
        f"promote 关时 capability.promoted 不应被累加，stat_counts={host.stat_counts}"
    )
