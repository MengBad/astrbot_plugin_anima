"""v0.9.10 Layer 1 晋升接线示例测试（EXAMPLE / 集成，非 Hypothesis 属性测试）。

被测编排器：CapabilitiesMixin._refresh_capability_tool_belt（经子类化 tests/_cap_host.CapHost）。
配合真实纯函数 _select_promotion_set / _capability_value_score。

约定（沿用 tests/_cap_host.py）：types.ModuleType 桩 astrbot.*，最小宿主类，
内存模拟 personal_capabilities.json，不依赖真实 astrbot 运行时。

覆盖行为（每项 1 个代表性示例）：
- 一次真实新注册使 capability.promoted +1（R1.8）
- capability_system_enabled=false → no-op（R2.2）
- 同名已注册 → 不重复注册（R2.3）
- 注册抛异常被吞、主流程继续（R2.4）

Requirements: 1.8, 2.2, 2.3, 2.4
"""
from datetime import datetime

from _cap_host import CapHost

TODAY = datetime.now().strftime("%Y-%m-%d")


def _make_cap(cap_id="cap_1", name="写诗"):
    """构造一条合法能力字典（字段足够 _capability_value_score 计算）。"""
    return {
        "id": cap_id,
        "name": name,
        "description": f"{name}的能力描述",
        "usage_count": 1,
        "corrections": [],
        "last_updated": datetime.now().isoformat(),
    }


class _WiringHost(CapHost):
    """晋升接线测试宿主基类：内存模拟注册计数 + 埋点计数。

    默认 _dynamically_register_capability_as_tool 实现：成功注册 →
    append 到 self.registered 并 self._daily_tool_register["count"] += 1
    （复用真实编排器靠前后差值判定"真实新注册"的语义）。
    """

    def __init__(self, config=None, caps=None):
        super().__init__(config=config, caps=caps)
        self._daily_tool_register = {"date": TODAY, "count": 0}
        self._promoted_cap_ids = set()
        self.registered = []
        self.stat_counts = {}

    def _stat_bump(self, key, n=1):
        self.stat_counts[key] = self.stat_counts.get(key, 0) + n

    def _dynamically_register_capability_as_tool(self, capability, force=False):
        # 默认：真实新注册（递增计数、记录）。
        self.registered.append(capability.get("id"))
        self._daily_tool_register["count"] += 1


class _DupNameHost(_WiringHost):
    """同名已注册场景：目标工具名已存在 → 跳过（不递增计数、不记录）。"""

    def __init__(self, config=None, caps=None, existing_names=None):
        super().__init__(config=config, caps=caps)
        self._existing_names = set(existing_names or [])

    def _dynamically_register_capability_as_tool(self, capability, force=False):
        # 模拟既有 _dynamically_register_capability_as_tool 的"同名跳过"：
        # 目标名已存在 → 直接返回，不递增 count、不记录（编排器据此不算晋升）。
        name = capability.get("name")
        if name in self._existing_names:
            return
        self._existing_names.add(name)
        self.registered.append(capability.get("id"))
        self._daily_tool_register["count"] += 1


class _RaisingHost(_WiringHost):
    """注册抛异常场景：register 内部抛出，验证编排器吞异常不外抛。"""

    def _dynamically_register_capability_as_tool(self, capability, force=False):
        raise RuntimeError("注册内部炸了")


def test_one_real_registration_bumps_promoted_once():
    """一次真实新注册使 capability.promoted +1（R1.8）。

    promote 开、system 开、单能力、配额可用：刷新后恰好发生一次注册，
    stat_counts["capability.promoted"] == 1，且能力 id 进入 _promoted_cap_ids。
    """
    cap = _make_cap()
    host = _WiringHost(
        config={
            "capability_system_enabled": True,
            "capability_promote_enabled": True,
            "capability_promote_top_k": 3,
        },
        caps=[cap],
    )

    host._refresh_capability_tool_belt()

    assert host.registered == ["cap_1"]                       # 恰好一次注册
    assert host.stat_counts.get("capability.promoted") == 1   # R1.8
    assert "cap_1" in host._promoted_cap_ids                  # 进程内已晋升集合


def test_system_disabled_is_noop():
    """capability_system_enabled=false → no-op（R2.2）。

    系统关闭（即便晋升开关打开）：刷新不注册、不累加任何埋点。
    """
    host = _WiringHost(
        config={
            "capability_system_enabled": False,
            "capability_promote_enabled": True,
            "capability_promote_top_k": 3,
        },
        caps=[_make_cap()],
    )

    host._refresh_capability_tool_belt()

    assert host.registered == []                              # 零注册
    assert host.stat_counts == {}                             # 零埋点
    assert host._promoted_cap_ids == set()


def test_duplicate_name_not_double_registered():
    """同名已注册 → 不重复注册（R2.3）。

    目标工具名已存在：register 跳过（不递增计数）；刷新后 capability.promoted
    的前后差值为 0（未被累加）。
    """
    cap = _make_cap(cap_id="cap_dup", name="已存在的能力")
    host = _DupNameHost(
        config={
            "capability_system_enabled": True,
            "capability_promote_enabled": True,
            "capability_promote_top_k": 3,
        },
        caps=[cap],
        existing_names={"已存在的能力"},
    )

    before = host.stat_counts.get("capability.promoted", 0)
    host._refresh_capability_tool_belt()
    after = host.stat_counts.get("capability.promoted", 0)

    assert host.registered == []                              # 同名 → 未重复注册
    assert after - before == 0                                # promoted 未被累加
    assert "cap_dup" not in host._promoted_cap_ids


def test_registration_exception_is_swallowed():
    """注册抛异常被吞、主流程继续（R2.4）。

    register 内部抛异常时，_refresh_capability_tool_belt 内部 try/except 兜底，
    绝不向外抛；埋点不被累加。
    """
    host = _RaisingHost(
        config={
            "capability_system_enabled": True,
            "capability_promote_enabled": True,
            "capability_promote_top_k": 3,
        },
        caps=[_make_cap(cap_id="cap_boom", name="会炸的能力")],
    )

    # 不应抛出任何异常
    host._refresh_capability_tool_belt()

    assert host.stat_counts.get("capability.promoted", 0) == 0
    assert "cap_boom" not in host._promoted_cap_ids
