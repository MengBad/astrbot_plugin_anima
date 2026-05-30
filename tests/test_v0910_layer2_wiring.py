"""v0.9.10 Layer 2 定向提示接线示例测试（EXAMPLE / 集成，非 Hypothesis 属性测试）。

被测接线：main.py `on_llm_request`（task 5.1）在 `caps_injection` 注入之后追加的
定向提示注入块。该块嵌在一个大型 hook 内不便直接单测，故此处用一个小宿主
（子类化 tests/_cap_host.CapHost）+ 一个**逐字镜像生产接线**的测试 helper
`_inject_hint`，通过真实纯函数 `_build_capability_hint` / `_compute_capability_relevance`
验证等价的"闸门 → 读能力 → 阈值/后端 → 构建提示 → append + 计数"门控行为。

约定（沿用 tests/_cap_host.py）：types.ModuleType 桩 astrbot.*，最小宿主类，
内存模拟 personal_capabilities.json，不依赖真实 astrbot 运行时。

覆盖行为（每项 1 个代表性示例）：
- 命中能力 → 注入提示串（含能力名）并 bump capability.match.hint_injected（R3.8）
- 未命中（高阈值）→ 不注入、不计数
- capability_match_hint_enabled=false → 不计算、不注入、不计数（R3.9）

Requirements: 3.8, 3.9
"""
from _cap_host import CapHost


class _Layer2WiringHost(CapHost):
    """最小宿主：内存模拟能力库 + `_stat_bump` 记录到 dict。"""

    def __init__(self, config=None, caps=None):
        super().__init__(config=config, caps=caps)
        self.stat_counts = {}

    def _stat_bump(self, key, n=1):
        self.stat_counts[key] = self.stat_counts.get(key, 0) + n


def _inject_hint(host, event_text):
    """逐字镜像 main.py `on_llm_request`（task 5.1）的定向提示注入块。

    生产代码结构：闸门 capability_match_hint_enabled → 读能力 → 取 threshold/backend
    → 调真实 `_build_capability_hint(..., embed_fn=None)` → 命中则 append 到
    injection_parts 并 `_stat_bump("capability.match.hint_injected")`。

    返回本次新增的 injection_parts（命中时含一条提示，否则为空列表）。
    """
    injection_parts = []
    if host.config.get("capability_match_hint_enabled", True):
        caps = host._read_personal_capabilities().get("capabilities", [])
        if caps:
            threshold = float(host.config.get("capability_match_hint_threshold", 0.2))
            backend = host.config.get("capability_match_hint_backend", "lexical")
            hint = host._build_capability_hint(
                event_text, caps, threshold, backend=backend, embed_fn=None
            )
            if hint:
                injection_parts.append(hint)
                host._stat_bump("capability.match.hint_injected")
    return injection_parts


def _make_cap(name="天气查询", when_to_use="查询天气预报", description="可以联网查天气"):
    return {
        "id": "cap_weather",
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
        "usage_count": 1,
        "corrections": [],
    }


def test_hit_injects_hint_and_bumps_counter():
    """命中 → 注入提示并 bump capability.match.hint_injected（R3.8）。

    能力 when_to_use="查询天气预报" 与 user_text="帮我查询天气预报" 词法高度重叠，
    低阈值 0.1 必命中：返回的 injection_parts 含一条提示（且包含能力名），
    且计数恰好累加一次。
    """
    cap = _make_cap()
    host = _Layer2WiringHost(
        config={
            "capability_match_hint_enabled": True,
            "capability_match_hint_threshold": 0.1,
            "capability_match_hint_backend": "lexical",
        },
        caps=[cap],
    )

    parts = _inject_hint(host, "帮我查询天气预报")

    assert len(parts) == 1                                       # 命中 → 注入一条
    assert cap["name"] in parts[0]                               # 提示指向 argmax 能力
    assert host.stat_counts.get("capability.match.hint_injected") == 1  # R3.8


def test_miss_with_high_threshold_no_injection_no_count():
    """未命中（高阈值）→ 不注入、不计数。

    user_text 与能力无关 + 阈值 0.9：最高相关性 < 阈值，提示为空串，
    injection_parts == []，计数键不出现。
    """
    host = _Layer2WiringHost(
        config={
            "capability_match_hint_enabled": True,
            "capability_match_hint_threshold": 0.9,
            "capability_match_hint_backend": "lexical",
        },
        caps=[_make_cap()],
    )

    parts = _inject_hint(host, "今天晚上吃点什么好呢")

    assert parts == []                                          # 不命中零提示
    assert "capability.match.hint_injected" not in host.stat_counts  # 未计数


def test_disabled_flag_skips_all():
    """capability_match_hint_enabled=false → 不计算、不注入、不计数（R3.9）。

    即便存在完美匹配的能力，关闭开关后整段被跳过：injection_parts == []，
    无计数累加。
    """
    host = _Layer2WiringHost(
        config={
            "capability_match_hint_enabled": False,
            "capability_match_hint_threshold": 0.0,
            "capability_match_hint_backend": "lexical",
        },
        caps=[_make_cap()],
    )

    parts = _inject_hint(host, "帮我查询天气预报")

    assert parts == []                                          # 关则不注入
    assert host.stat_counts == {}                               # R3.9：无额外计算/计数
