"""v0.9.10 Layer 3 `when_to_use` 示例测试（EXAMPLE / 集成，非 Hypothesis 属性测试）。

覆盖 Layer 3「合成质量：要求 when_to_use」的接线与字段流转，用 1-3 个代表性示例
（不对纯接线做 100 次迭代）。约定沿用 tests/_cap_host.py：types.ModuleType 桩 astrbot.*，
最小宿主类 CapHost，内存模拟 personal_capabilities.json，不依赖真实 astrbot 运行时。

覆盖行为：
- Case 1：danger.py 两处合成 prompt 模板均含 when_to_use 字段指令（R4.1）
- Case 2：_create_or_update_capability 透传并持久化 when_to_use；UPDATE 分支可更新（R4.2）
- Case 3：缺 when_to_use 的存量能力可正常创建/注入/匹配，Match_Text 回退 description
          （R4.4, R6.1, R6.2）

Requirements: 4.1, 4.2, 4.4, 6.1, 6.2
"""
import os

from _cap_host import CapHost

DANGER_PATH = os.path.join(os.path.dirname(__file__), "..", "anima", "mixins", "danger.py")


def _read_danger_source() -> str:
    with open(DANGER_PATH, encoding="utf-8") as f:
        return f.read()


# ----------------------------------------------------------------------------
# Case 1：合成 prompt 模板含 when_to_use（R4.1）
# ----------------------------------------------------------------------------
def test_synthesis_prompts_contain_when_to_use_field():
    """danger.py 两处合成 prompt 的 JSON 模板都要求输出 when_to_use 字段（R4.1）。

    两个独立但互补的鲁棒断言：
    - JSON 字段 token `"when_to_use"`（含引号）至少出现两次（每个合成站点一次）。
    - 字段指令文案「描述这个能力适用的具体触发场景」至少出现两次。
    """
    src = _read_danger_source()

    # JSON 字段 token（含起始引号），每处合成模板各一 → >= 2。
    assert src.count('"when_to_use"') >= 2

    # 字段指令文案，每处合成模板各一 → >= 2。
    assert src.count("描述这个能力适用的具体触发场景") >= 2


# ----------------------------------------------------------------------------
# Case 2：_create_or_update_capability 透传并持久化 when_to_use（R4.2）
# ----------------------------------------------------------------------------
def test_create_persists_when_to_use():
    """新建能力时 when_to_use 作为普通键被透传并持久化（R4.2）。"""
    host = CapHost(config={"capability_system_enabled": True})

    host._create_or_update_capability({
        "name": "天气查询",
        "description": "查天气",
        "when_to_use": "用户问天气时",
    })

    caps = host._read_personal_capabilities()["capabilities"]
    stored = next(c for c in caps if c.get("name") == "天气查询")
    assert stored["when_to_use"] == "用户问天气时"


def test_update_branch_updates_when_to_use():
    """UPDATE 分支（同名再次创建）可更新 when_to_use（R4.2）。

    更新分支 `old.update(...)` 仅排除 corrections/usage_count，when_to_use 作为
    普通键随之更新。
    """
    host = CapHost(config={"capability_system_enabled": True})

    host._create_or_update_capability({
        "name": "天气查询",
        "description": "查天气",
        "when_to_use": "用户问天气时",
    })
    # 同名再次创建 → 走更新分支，提供新的 when_to_use。
    host._create_or_update_capability({
        "name": "天气查询",
        "description": "查天气",
        "when_to_use": "用户想知道明天会不会下雨时",
    })

    caps = host._read_personal_capabilities()["capabilities"]
    matches = [c for c in caps if c.get("name") == "天气查询"]
    assert len(matches) == 1                                     # 同名合并，不新增
    assert matches[0]["when_to_use"] == "用户想知道明天会不会下雨时"  # 已更新


# ----------------------------------------------------------------------------
# Case 3：缺 when_to_use 的存量能力可正常创建/注入/匹配（R4.4, R6.1, R6.2）
# ----------------------------------------------------------------------------
def test_missing_when_to_use_creates_and_matches_via_description_fallback():
    """缺 when_to_use 的能力照常创建，相关性计算回退 description（R4.4, R6.1, R6.2）。"""
    host = CapHost(config={"capability_system_enabled": True})

    # 不带 when_to_use 字段创建（模拟存量能力）。
    host._create_or_update_capability({
        "name": "天气助手",
        "description": "帮助用户查询天气预报信息",
    })

    caps = host._read_personal_capabilities()["capabilities"]
    stored = next(c for c in caps if c.get("name") == "天气助手")
    assert "when_to_use" not in stored                          # 缺字段，照常入库（R6.1）
    assert stored["description"] == "帮助用户查询天气预报信息"   # 既有字段语义不变（R6.2）

    # 相关性计算不报错；Match_Text 回退 description：与描述重叠的文本得分 > 0。
    idx_hit, score_hit = host._compute_capability_relevance("天气预报", caps)
    assert idx_hit == 0
    assert score_hit > 0.0                                       # 命中 description 回退

    # 无重叠文本得分为 0（同样不报错）。
    idx_miss, score_miss = host._compute_capability_relevance("zzzzz", caps)
    assert score_miss == 0.0


def test_missing_when_to_use_injection_does_not_error():
    """缺 when_to_use 的能力进入上下文注入不报错且含能力名（R4.4）。"""
    host = CapHost(config={"capability_system_enabled": True})
    host._create_or_update_capability({
        "name": "天气助手",
        "description": "帮助用户查询天气预报信息",
    })

    injection = host._get_personal_capabilities_injection()
    assert isinstance(injection, str)
    assert "天气助手" in injection
