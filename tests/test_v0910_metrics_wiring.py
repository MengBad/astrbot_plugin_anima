"""v0.9.10 度量 gate 示例/冒烟测试（SMOKE / EXAMPLE，非 Hypothesis 属性测试）。

被测接线：CapabilitiesMixin._execute_single_capability 的 capability.call.* 埋点，
经【真实】StatsMixin._stat_bump —— 其 dashboard_enabled gate 决定计数是否累加。

属性（来自 design.md「度量 gate（SMOKE）」+ 错误处理表 R5.5）：
- dashboard_enabled=false → capability.call.* 计数不累加，且 _stat_bump 吞异常绝不外抛。
- dashboard_enabled=true（sanity）→ capability.call.attempt 确实被累加，
  证明「是 gate 抑制了计数」，而非接线本身坏掉。

约定（沿用 tests/_cap_host.py）：types.ModuleType 桩 astrbot.*、最小宿主类、
内存模拟 personal_capabilities.json，不依赖真实 astrbot 运行时。本测试额外混入
【真实】StatsMixin，让 _execute_single_capability 走真实 _stat_bump 行为。

Validates: Requirements 5.5
"""
import asyncio

# 先 import _cap_host：安装 astrbot.* 桩并触发 CapabilitiesMixin 导入。
import _cap_host  # noqa: F401
from _cap_host import CapHost

# 真实 StatsMixin（含真实 _stat_bump 的 dashboard_enabled gate + 吞异常）。
from anima.mixins.stats import StatsMixin

# _cap_host 把 astrbot.core.agent.tool.ToolExecResult 桩成了 object，
# 而 _execute_single_capability 会 ToolExecResult(result=...)；object 不接受 kwargs
# 会抛 TypeError。替换 capabilities 模块命名空间里的 ToolExecResult 为可接受 result 的
# 轻量真实类，使「不抛异常」的断言真正反映 gate 行为而非桩缺陷。
import anima.mixins.capabilities as _cap_mod


class _ToolExecResult:
    def __init__(self, result=None, **_kw):
        self.result = result


_cap_mod.ToolExecResult = _ToolExecResult


EXISTING_NAME = "写诗"
MISSING_NAME = "completely_unrelated_zzz_capability"


def _make_cap(cap_id="cap_1", name=EXISTING_NAME):
    return {
        "id": cap_id,
        "name": name,
        "description": f"{name}的能力描述",
        "how_to_use": "按步骤产出结果",
        "usage_count": 1,
        "corrections": [],
    }


class MetricsHost(StatsMixin, CapHost):
    """混入【真实】StatsMixin + CapabilitiesMixin 的最小宿主。

    - _stat_bump：来自真实 StatsMixin（MRO 中 StatsMixin 在前），受 dashboard_enabled 控制。
    - _ensure_stats_loaded 依赖 _load_state；_stat_bump 持久化依赖 _atomic_update_state。
      这里提供最小内存实现，让真实 _stat_bump 完整跑通（含懒持久化分支）。
    - _get_provider_id 返回 ""：_execute_single_capability 跳过真实 LLM/context。
    """

    def __init__(self, config=None, caps=None):
        CapHost.__init__(self, config=config, caps=caps)
        self._state = {}  # 内存 state，供真实 StatsMixin 读写

    # --- StatsMixin 依赖的最小内存 state 接线 ---
    def _load_state(self):
        return dict(self._state)

    def _atomic_update_state(self, fn):
        fn(self._state)

    # --- 避免真实 LLM/context ---
    async def _get_provider_id(self, event):
        return ""


def _drive(host):
    """用 asyncio 驱动两次调用：一个可解析名 + 一个不可解析名。返回是否抛异常。"""
    async def _run():
        await host._execute_single_capability(EXISTING_NAME, "args")     # resolved 路径
        await host._execute_single_capability(MISSING_NAME, "args")      # unresolved 路径

    asyncio.run(_run())


def test_metrics_suppressed_when_dashboard_disabled():
    """Case 1：dashboard_enabled=false → capability.call.* 不累加且不抛异常（R5.5）。"""
    host = MetricsHost(config={"dashboard_enabled": False}, caps=[_make_cap()])

    # 驱动调用——真实 _stat_bump 应在 gate 处提前 return，绝不抛异常。
    _drive(host)  # 若抛异常，测试在此失败

    # 真实 StatsMixin 读取接口：三个计数均为 0。
    assert host._stats_get("capability.call.attempt") == 0
    assert host._stats_get("capability.call.resolved") == 0
    assert host._stats_get("capability.call.unresolved") == 0

    # 快照里完全没有 capability.call.* key（不仅是 0，而是从未写入）。
    raw = host._stats_snapshot()["raw"]
    assert not any(k.startswith("capability.call.") for k in raw)


def test_metrics_counted_when_dashboard_enabled():
    """Case 2（sanity）：dashboard_enabled=true → attempt 被累加，证明 gate 才是抑制因。"""
    host = MetricsHost(config={"dashboard_enabled": True}, caps=[_make_cap()])

    _drive(host)

    # 两次调用 → attempt 累加 2 次；一次可解析、一次不可解析。
    assert host._stats_get("capability.call.attempt") == 2
    assert host._stats_get("capability.call.resolved") == 1
    assert host._stats_get("capability.call.unresolved") == 1
