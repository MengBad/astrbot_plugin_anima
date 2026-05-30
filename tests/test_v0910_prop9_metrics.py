# Feature: capability-loop-strengthening, Property 9: 调用埋点互斥穷尽 —— attempt == resolved + unresolved
"""v0.9.10 度量闭环 属性测试 —— Property 9：调用埋点互斥穷尽。

被测真实执行路径：CapabilitiesMixin._execute_single_capability（task 7.2 埋点接线处）。
配合真实的 _read_personal_capabilities / _resolve_capability（均来自 mixin，不被覆盖）。

属性：对任意一串能力调用序列（可解析名与不可解析名混合），按"先 bump
`capability.call.attempt`，再依 `_resolve_capability` 结果 bump 恰好一个
`resolved`/`unresolved`"的模式累加后：
    capability.call.attempt == capability.call.resolved + capability.call.unresolved
即每次尝试被恰好分类一次（互斥穷尽）。并且 attempt 累加值恒等于实际发起的调用次数。

测试手法：子类化 tests/_cap_host.CapHost，记录 _stat_bump 到 self.stats，并让
_get_provider_id 返回 ""（空），使 resolved 分支在 bump `capability.call.resolved`
之后于 provider 闸门处优雅返回 fallback ToolExecResult —— 不触碰 self.context、
不发起任何真实 LLM 调用。用 asyncio.run 逐个驱动真实异步执行入口（沿用 tests/ 既有约定）。

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""
import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from _cap_host import CapHost

# tests/_cap_host.py 把 astrbot 的 ToolExecResult 桩为裸 `object`，无法接收 result= 关键字。
# _execute_single_capability 在两条返回路径都会构造 ToolExecResult(result=...)，故在本测试
# 内（不触碰其它文件）把 mixin 模块引用替换为可接收 result 的轻量替身。埋点逻辑不受影响。
import anima.mixins.capabilities as _capmod


class _ToolExecResult:
    def __init__(self, result=None, **kw):
        self.result = result


_capmod.ToolExecResult = _ToolExecResult


class StatCapHost(CapHost):
    """最小 stat 记录宿主：在真实执行路径上累加 capability.call.* 埋点。

    - _stat_bump：累加进 self.stats（断言所依赖的累加器）。
    - _get_provider_id：恒返回 ""（空）—— resolved 分支已在此之前 bump
      `capability.call.resolved`，随后于 provider 闸门优雅返回，不触碰 context/LLM。
    - _read_personal_capabilities / _resolve_capability / _execute_single_capability：
      来自 CapHost / mixin 的真实方法，不覆盖。
    """

    def __init__(self, config=None, caps=None):
        super().__init__(config=config, caps=caps)
        self.stats = {}

    def _stat_bump(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    async def _get_provider_id(self, event=None, prefer=""):
        # 返回空 → resolved 路径在 bump 之后于 provider 闸门优雅返回 fallback。
        return ""


# 已知能力名集合 —— 序列里命中这些名字即走 resolved 路径。
_PRESENT_NAMES = ["天气查询", "翻译", "code_review", "summarize", "calc"]


def _make_caps(names):
    return [
        {
            "id": f"cap_{i}",
            "name": name,
            "description": f"desc_{i}",
            "how_to_use": "do it",
            "usage_count": 0,
            "corrections": [],
            "last_updated": "2025-01-01T00:00:00",
        }
        for i, name in enumerate(names)
    ]


@st.composite
def call_scenario(draw):
    """随机种子能力子集 + 随机调用名序列（混合命中名与随机串）。

    调用名来自：已知能力名（倾向命中 resolved）或任意随机文本（多半 unresolved）。
    无论每次实际落入 resolved 还是 unresolved，互斥穷尽不变式都应成立 —— 这正是
    本属性要覆盖的输入空间。"""
    # 随机选取部分已知能力作为宿主种子（可能为空）。
    seeded = draw(st.lists(st.sampled_from(_PRESENT_NAMES), max_size=len(_PRESENT_NAMES), unique=True))
    caps = _make_caps(seeded)

    # 调用名序列：命中名 + 随机文本混合，长度 0..15。
    name_source = st.one_of(
        st.sampled_from(_PRESENT_NAMES),
        st.text(min_size=0, max_size=12),
    )
    names = draw(st.lists(name_source, min_size=0, max_size=15))
    return caps, names


@settings(max_examples=100, deadline=None)
@given(call_scenario())
def test_prop9_metrics_mutually_exclusive_exhaustive(scenario):
    caps, names = scenario

    host = StatCapHost(config={}, caps=caps)

    async def _drive():
        for name in names:
            await host._execute_single_capability(name, "args")

    asyncio.run(_drive())

    attempt = host.stats.get("capability.call.attempt", 0)
    resolved = host.stats.get("capability.call.resolved", 0)
    unresolved = host.stats.get("capability.call.unresolved", 0)

    # 不变式 1：互斥穷尽 —— 每次 attempt 恰好分类为 resolved 或 unresolved 之一。
    assert attempt == resolved + unresolved, (
        f"attempt({attempt}) != resolved({resolved}) + unresolved({unresolved})；"
        f" stats={host.stats}"
    )

    # 不变式 2：attempt 累加值恒等于实际发起的调用次数。
    assert attempt == len(names), (
        f"attempt({attempt}) != 调用次数({len(names)})；stats={host.stats}"
    )
