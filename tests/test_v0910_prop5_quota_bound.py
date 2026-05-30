# Feature: capability-loop-strengthening, Property 5: 晋升受配额上界约束 —— 新注册数 <= min(K, 当日剩余配额)
"""v0.9.10 Layer 1 属性测试 —— Property 5：晋升受配额上界约束。

被测编排器：CapabilitiesMixin._refresh_capability_tool_belt（经下方 QuotaCapHost）。

属性：对任意能力集合与当日已用配额，调用 `_refresh_capability_tool_belt` 本次因晋升而
新注册的 Named_Tool 数 `<= min(K, 当日剩余 dynamic_tool_daily_quota)`，且晋升候选集合
（能力工具带候选）大小 `<= K`。

测试手法：子类化 tests/_cap_host.CapHost，注入内存版 `_daily_tool_register` 计数与一个
忠实模拟「每日配额闸门 + 同名跳过 + 仅真实新注册才 +1」语义的假注册函数，避免真实
astrbot 调用。编排器靠注册前后 count 差值识别本次真实新注册，故该假注册函数的计数契约
正是 Property 5 上界约束所依赖的核心。

Validates: Requirements 1.6, 1.7
"""
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from _cap_host import CapHost


class QuotaCapHost(CapHost):
    """注入内存配额计数 + 假注册函数的最小宿主。

    忠实镜像真实 `_dynamically_register_capability_as_tool` 的配额闸门：
    - 跨天重置：date 不是今天则重置 count=0。
    - 超配额（count >= daily_quota）→ 直接返回，不注册、不增量计数。
    - 同名已注册 → 跳过，不增量计数。
    - 否则：记入 self.registered 并 count += 1（仅真实新注册才增量）。
    """

    def __init__(self, config, caps, already_used):
        super().__init__(config=config, caps=caps)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily_tool_register = {"date": today, "count": int(already_used)}
        self._promoted_cap_ids = set()
        self.registered = []          # 本次真实新注册的能力名（顺序记录）
        self._registered_names = set()  # 同名跳过用
        self.stats = {}                 # _stat_bump 记录

    def _stat_bump(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def _dynamically_register_capability_as_tool(self, capability, force=False):
        # 跨天重置（与真实实现一致）
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_tool_register.get("date") != today:
            self._daily_tool_register = {"date": today, "count": 0}
        daily_quota = int(self.config.get("dynamic_tool_daily_quota", 3))
        # 配额耗尽 → 不注册、不增量（能力仅入库）
        if self._daily_tool_register["count"] >= daily_quota:
            return
        name = capability.get("name", "unknown_cap")
        # 同名跳过 → 不增量（镜像真实的 any(t.name == safe_tool_name) 检查）
        if name in self._registered_names:
            return
        # 真实新注册 → 记录并增量计数
        self._registered_names.add(name)
        self.registered.append(name)
        self._daily_tool_register["count"] += 1


@st.composite
def quota_scenario(draw):
    """随机能力列表（唯一 id/name、varied value-score 输入）+ 随机 K / 已用配额 / 每日配额。"""
    n = draw(st.integers(min_value=0, max_value=12))
    caps = []
    for i in range(n):
        caps.append({
            "id": f"cap_{i}",
            "name": f"cap_{i}",            # 唯一名，避免同名跳过干扰上界
            "description": f"desc_{i}",
            "usage_count": draw(st.integers(min_value=0, max_value=50)),
            "corrections": ["c"] * draw(st.integers(min_value=0, max_value=5)),
            "last_updated": draw(st.sampled_from([
                "2024-01-01T00:00:00", "2025-01-01T00:00:00",
                "2023-06-15T12:00:00", "not-a-date", "",
            ])),
        })
    k = draw(st.integers(min_value=1, max_value=6))
    already_used = draw(st.integers(min_value=0, max_value=5))
    quota = draw(st.integers(min_value=1, max_value=5))
    return caps, k, already_used, quota


@settings(max_examples=100)
@given(quota_scenario())
def test_prop5_quota_bound(scenario):
    caps, k, already_used, quota = scenario

    config = {
        "capability_promote_enabled": True,
        "capability_system_enabled": True,
        "capability_promote_top_k": k,
        "dynamic_tool_daily_quota": quota,
    }
    host = QuotaCapHost(config=config, caps=caps, already_used=already_used)

    # 关键：在调用 refresh 之前捕获当日已用配额（编排器会增量它）。
    used_before = host._daily_tool_register.get("count", 0)
    remaining = max(0, quota - used_before)

    host._refresh_capability_tool_belt()

    # 不变量 1：本次新注册数 <= min(K, 当日剩余配额)。
    assert len(host.registered) <= min(k, remaining), (
        f"新注册数 {len(host.registered)} 超过上界 min(K={k}, remaining={remaining})；"
        f" used_before={used_before}, quota={quota}, registered={host.registered}"
    )

    # 不变量 2：晋升候选集合（能力工具带候选）大小 <= K。
    candidates = host._select_promotion_set(caps, k, set())
    assert len(candidates) <= k, (
        f"晋升候选集合大小 {len(candidates)} 超过 K={k}"
    )
