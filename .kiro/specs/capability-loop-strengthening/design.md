# Design Document

## Overview

本特性（Anima v0.9.10）闭合个人能力系统的**使用闭环**。生产实测 105 个能力 / 0 次调用，根因三条：置信度死锁（可发现性）、纯靠模型自觉（意愿）、能力描述含糊（质量）。

设计遵循 Anima 既有约定：

- **Mixin 架构**：新增方法落在 `anima/mixins/capabilities.py`（`CapabilitiesMixin`），不新建子系统。
- **纯函数优先**：把可测的核心逻辑抽成**无 I/O、无 LLM、无 config 读取**的纯函数（`_select_promotion_set`、`_compute_capability_relevance`、`_build_capability_hint`），由薄的"非纯编排器"包裹。属性测试只测纯函数。
- **Hypothesis 属性测试** + `types.ModuleType` 桩（沿用 `tests/_cap_host.py` 约定）。
- **三个新开关默认值遵循项目约定**：高 token 特性默认关（晋升），免费特性默认开（提示、`when_to_use`）。

整体改动是**加法且默认安全**：`capability_promote_enabled=false` 时行为与 v0.9.4 完全一致（零回归）。

### 三层 + 度量闭环映射

| 层 | 目标 | 纯函数 | 编排器 / 接线点 | 默认 |
|----|------|--------|-----------------|------|
| Layer 1 晋升 | 可发现性 | `_select_promotion_set` | `_refresh_capability_tool_belt` ← `initialize()` / `_maintain_capabilities_health()` | OFF |
| Layer 2 定向提示 | 意愿 | `_compute_capability_relevance` / `_build_capability_hint` | `on_llm_request`（main.py ~603） | ON |
| Layer 3 when_to_use | 质量 | （字段流转，无新纯函数） | `danger.py` 两处合成 + `_create_or_update_capability` | ON |
| 度量闭环 | 可观测 | （计数不变式） | dispatcher `call` + `_execute_single_capability` + `_refresh_capability_tool_belt` + `on_llm_request` | 随 `dashboard_enabled` |

## Architecture

```mermaid
flowchart TD
    subgraph L1[Layer 1 晋升 - 可发现性]
        INIT[initialize] --> RB[_refresh_capability_tool_belt]
        HM[_maintain_capabilities_health] --> RB
        RB -->|gate: system_enabled AND promote_enabled| SEL[_select_promotion_set 纯]
        SEL -->|Top-K + Trial_Slot| RB
        RB -->|每个新名| REG[_dynamically_register_capability_as_tool]
        RB -->|成功注册| M1[(stat: capability.promoted)]
    end

    subgraph L2[Layer 2 定向提示 - 意愿]
        OLR[on_llm_request ~603] --> INJ[_get_personal_capabilities_injection]
        OLR -->|hint_enabled AND caps| HINT[_build_capability_hint]
        HINT --> REL[_compute_capability_relevance 纯]
        HINT -->|score >= threshold| APPEND[append 到 injection_parts]
        APPEND --> M2[(stat: capability.match.hint_injected)]
    end

    subgraph L3[Layer 3 when_to_use - 质量]
        SYN[danger.py 合成 x2] -->|prompt 增字段| COU[_create_or_update_capability]
        COU -->|when_to_use 流转持久化| STORE[(personal_capabilities.json)]
        STORE -.Match_Text 优先 when_to_use.-> REL
    end

    subgraph LM[度量闭环]
        DISP[dispatcher call] --> RES[_resolve_capability]
        ESC[_execute_single_capability] --> RES
        RES --> M3[(stat: call.attempt + resolved|unresolved)]
    end
```

### 关键架构决策

**决策 1：晋升与旧 `confidence >= 0.65` 自动注册如何共存（避免双重注册）。**

`_create_or_update_capability` 现有逻辑：当 `confidence >= 0.65` 且 `register_as_independent_tool=True` 时调 `_dynamically_register_capability_as_tool`。该路径保持不变。晋升是**独立的发现机制**：

- `capability_promote_enabled=false`（默认）：晋升完全不运行，注册行为退化为 v0.9.4 既有逻辑（R2.1，零回归）。
- `capability_promote_enabled=true`：`_refresh_capability_tool_belt` 成为补充发现机制，按 Value_Score 取 Top-K 注册。**去重靠 `_dynamically_register_capability_as_tool` 内已存在的"同名工具跳过"检查**（`any(t.name == safe_tool_name ...)`），因此晋升与旧自动注册即便选中同一能力也只注册一次（R2.3）。两条路径调用同一个注册函数，天然不会双注册。

为让晋升能注册 `confidence < 0.65` 的能力，晋升路径**不经过** `_create_or_update_capability` 的 0.65 闸门——它直接调 `_dynamically_register_capability_as_tool(cap)`。但该函数内部仍有 `register_as_independent_tool` 闸门。为不破坏旧语义又允许晋升，采用**小重构**：给 `_dynamically_register_capability_as_tool` 增加可选参数 `force: bool = False`；晋升路径以 `force=True` 调用，跳过 `register_as_independent_tool` 标记检查，但**仍尊重** `dynamic_tool_registration_enabled` 否？——见决策 2。

**决策 2：晋升是否要求 `dynamic_tool_registration_enabled`。**

晋升的目的就是打破死锁、让能力被注册成命名工具。`dynamic_tool_registration_enabled` 默认 false。若晋升仍要求它，则晋升默认不可用且需用户开两个开关。结论：**晋升路径不要求 `dynamic_tool_registration_enabled`**，仅由 `capability_promote_enabled` 单独控制（语义清晰：开晋升即开启工具带）。但**仍尊重** `dynamic_tool_daily_quota`（R1.6）与同名跳过（R2.3）。实现上 `force=True` 同时跳过 `dynamic_tool_registration_enabled` 与 `register_as_independent_tool` 两个闸门，但配额与同名检查照常生效。

**决策 3："从未被晋升过"的追踪方式。**

选用**进程内集合** `self._promoted_cap_ids: set[str]`（在 `__init__` 初始化）。

- 理由：Trial_Slot 是"让新能力在本进程生命周期内获得至少一次曝光"的运行期调度，不是需要跨重启持久的领域数据。用集合避免污染 `personal_capabilities.json`、避免新增持久字段及其迁移成本。
- 权衡：进程重启后集合清空，已晋升过的新能力可能再次占用 Trial_Slot。这是可接受的——重启后让其再曝光一次无害，反而保证刚重启时新能力仍可见。
- 可测性：为保持 `_select_promotion_set` 纯，**把 `already_promoted_ids` 作为显式参数传入**，而非读 `self`。编排器负责传 `self._promoted_cap_ids`，纯函数只对入参负责。

## Components and Interfaces

### Layer 1：晋升

#### 纯函数 `_select_promotion_set`（capabilities.py）

```python
def _select_promotion_set(
    self,
    capabilities: list,
    k: int,
    already_promoted_ids: set | None = None,
    now=None,
) -> list:
    """纯函数：从 capabilities 选出至多 k 个待晋升能力。
    - 仅按 _capability_value_score 降序排序（不读 confidence）。
    - 至多返回 k 个。
    - Trial_Slot：若存在 usage_count==0 且 id 不在 already_promoted_ids 的"新能力"，
      保证返回集合中至少含一个这样的新能力。
    无 I/O、无 LLM、无 config 读取。now 可注入以保证确定性。
    """
```

算法（确定性、可测）：

1. `now = now or datetime.now()`；`already_promoted_ids = already_promoted_ids or set()`。
2. `k <= 0` 或空集合 → 返回 `[]`。
3. 按 `_capability_value_score(cap, now)` 降序稳定排序得到 `ranked`（同分时按原始顺序，保证确定性）。
4. `top = ranked[:k]`。
5. Trial_Slot 处理：
   - `newcomers = [c for c in ranked if (c.get("usage_count",0) or 0)==0 and c.get("id") not in already_promoted_ids]`。
   - 若 `newcomers` 非空且 `top` 中不含任何 newcomer 且 `k >= 1`：取 `top` 的前 `k-1` 个，追加 `newcomers[0]`（价值分最高的新能力），构成新的至多 k 个集合。
6. 返回该集合（长度 `<= k`）。

> 注：`_capability_value_score` 已是 `self` 上的纯方法（只依赖入参与 `now`），可在纯函数内安全调用。

#### 编排器 `_refresh_capability_tool_belt`（capabilities.py，非纯）

```python
def _refresh_capability_tool_belt(self):
    """晋升刷新：按 Value_Score Top-K 注册命名工具。整体 try/except 包裹，失败不影响主流程。"""
    try:
        if not self.config.get("capability_system_enabled", True):
            return                                  # R2.2
        if not self.config.get("capability_promote_enabled", False):
            return                                  # R2.1 / Property 4：默认关，零新注册
        caps = self._read_personal_capabilities().get("capabilities", [])
        if not caps:
            return
        k = int(self.config.get("capability_promote_top_k", 3))
        selected = self._select_promotion_set(caps, k, self._promoted_cap_ids)
        for cap in selected:
            before = self._daily_tool_register.get("count", 0)
            self._dynamically_register_capability_as_tool(cap, force=True)  # 含配额/同名检查
            after = self._daily_tool_register.get("count", 0)
            if after > before:                       # 仅真正新注册才算晋升
                self._promoted_cap_ids.add(cap.get("id", ""))
                self._stat_bump("capability.promoted")  # R1.8
    except Exception as e:
        logger.debug(f"[Anima] 能力工具带刷新异常: {e}")   # R2.4
```

注册成功判定：复用 `_dynamically_register_capability_as_tool` 已有的"成功注册才 `self._daily_tool_register['count'] += 1`"语义，通过比较计数前后差值精确识别**本次新注册**（跳过的同名/超配额不增量），从而 `capability.promoted` 只在真实新增时累加，且工具带大小受 K 与配额双重约束（R1.6、R1.7、Property 5）。

#### 小重构 `_dynamically_register_capability_as_tool(self, capability, force=False)`

```python
def _dynamically_register_capability_as_tool(self, capability: dict, force: bool = False):
    if not force:
        if not self.config.get("dynamic_tool_registration_enabled", False):
            return
        if not capability.get("register_as_independent_tool", False):
            return
    # force=True（晋升路径）：跳过上述两个标记闸门，
    # 但以下"每日配额检查"与"同名跳过"对两条路径都保留不变。
    ...  # 既有逻辑（配额、归一化、同名跳过、add_llm_tools）保持
```

> 既有调用方（`_create_or_update_capability` 内）不传 `force`，行为完全不变 → 既有 `_dynamically_register_capability_as_tool` 测试与 `_create_or_update_capability` 测试仍有效（R7.1）。

#### 接线点

- `initialize()`：在 `_migrate_capabilities_v094()` 之后追加 `self._refresh_capability_tool_belt()`（try/except 内）。
- `_maintain_capabilities_health()`：方法末尾追加 `self._refresh_capability_tool_belt()`。

### Layer 2：相关性触发的定向提示

#### 纯函数 `_compute_capability_relevance`（capabilities.py）

```python
def _compute_capability_relevance(
    self,
    user_text: str,
    capabilities: list,
    *,
    backend: str = "lexical",
    embed_fn=None,
) -> tuple[int, float]:
    """纯/确定性（lexical 路径）：返回 (best_index, best_score)。
    - 每个能力的 Match_Text = when_to_use（存在且非空）否则 description（Property 8）。
    - lexical：用 anima.similarity.text_jaccard(user_text, match_text)。
    - backend=="embedding" 且 embed_fn 提供：用注入的 embed_fn 计算；
      embed_fn 缺失或抛异常 → 降级 text_jaccard，绝不抛异常（Property 7）。
    - 空能力集 → (-1, 0.0)。分值有限非负。
    """
```

要点：

- Match_Text 选择：`(cap.get("when_to_use") or "").strip() or cap.get("description","")`。
- lexical 使用 `from ..similarity import text_jaccard`（已验证存在，是 `jaccard_similarity(text_token_set(a), text_token_set(b))` 的便捷封装）。
- embedding 路径通过**注入的 `embed_fn`** 保持纯函数可测：编排器在线上传入一个同步包装；测试可传 `None`（降级）或抛异常的 fn（验证不抛、降级）。任何异常都 `try/except` 后回退 lexical。
- 返回有限非负 `best_score`（`0.0` 当无能力或全 0）。

#### 纯函数 `_build_capability_hint`（capabilities.py）

```python
def _build_capability_hint(
    self,
    user_text: str,
    capabilities: list,
    threshold: float,
    *,
    backend: str = "lexical",
    embed_fn=None,
) -> str:
    """命中返回定向提示串，否则返回 ""。比较逻辑纯。"""
    idx, score = self._compute_capability_relevance(
        user_text, capabilities, backend=backend, embed_fn=embed_fn)
    if idx < 0 or score < threshold:
        return ""                                   # Property 6：不命中零提示
    name = capabilities[idx].get("name", "未命名能力")
    return f"用户当前的需求很可能匹配你的能力「{name}」——优先考虑调用它。"
```

> threshold 由编排器从 config 读出后传入，核心比较保持纯（便于属性测试用任意 threshold）。

#### 接线点 `on_llm_request`（main.py ~603）

在 `caps_injection = self._get_personal_capabilities_injection()` 之后：

```python
caps_injection = self._get_personal_capabilities_injection()
if caps_injection:
    injection_parts.append(caps_injection)
    # Layer 2: 相关性触发的定向提示
    try:
        if self.config.get("capability_match_hint_enabled", True):   # R3.9 关则跳过
            caps = self._read_personal_capabilities().get("capabilities", [])
            if caps:
                user_text = event.message_str if event and hasattr(event, "message_str") else ""
                threshold = float(self.config.get("capability_match_hint_threshold", 0.2))
                backend = self.config.get("capability_match_hint_backend", "lexical")
                hint = self._build_capability_hint(user_text, caps, threshold, backend=backend, embed_fn=None)
                if hint:
                    injection_parts.append(hint)
                    self._stat_bump("capability.match.hint_injected")  # R3.8
    except Exception as e:
        logger.debug(f"[Anima] 能力定向提示注入异常: {e}")
```

> embedding 在线包装可作为后续增强；首版 `embed_fn=None` 即 lexical（默认后端），`backend="embedding"` 在缺 fn 时自动降级（R3.7），不阻塞交付。

### Layer 3：合成时要求 when_to_use

- **`danger.py` 两处合成提示**（`_do_self_directed_research`、`_danger_autonomous_web`）：在 JSON 模板新增 `"when_to_use": "描述这个能力适用的具体触发场景（什么样的用户需求/情境下该用它）"`，并在 `cap_payload` 透传：`if "when_to_use" in cap_data: cap_payload["when_to_use"] = str(cap_data["when_to_use"])[:300]`。
- **`_create_or_update_capability`**：当前用 `old.update({k:v ...})`（更新分支）与 `cap_list.append(capability)`（新建分支）通吃所有键，`when_to_use` 作为普通键**自动流转持久化**，不被剥离（R4.2）。无需特殊处理；设计仅需确认它不在任何 drop-list 中——当前更新分支仅排除 `corrections`/`usage_count`，新建分支无排除，故 `when_to_use` 安全通过。
- **向后兼容**：缺失 `when_to_use` 的存量能力，Match_Text 回退 `description`（R4.3、Property 8），创建/注入/匹配/调用全链路不报错（R4.4）。

### 度量闭环

`capability.call.*` 埋点需保证**每次 attempt 恰好对应一次 resolved 或 unresolved**（互斥穷尽，Property 9）。统一模式：先 `attempt`，再依 `_resolve_capability` 结果 bump 恰好一个。

**接线点 A — dispatcher `call`（main.py，`AnimaPersonalCapabilityDispatcher`）：**

```python
plugin._stat_bump("capability.call.attempt")
target = plugin._resolve_capability(capability_name, caps.get("capabilities", []))
if not target:
    plugin._stat_bump("capability.call.unresolved")
    return ToolExecResult(result=f"[我的能力系统] 我目前没有叫「{capability_name}」的个人工具。")
plugin._stat_bump("capability.call.resolved")
```

**接线点 B — `_execute_single_capability`（capabilities.py，Named_Tool 路径）：**

```python
self._stat_bump("capability.call.attempt")
target = self._resolve_capability(capability_name, caps.get("capabilities", []))
if not target:
    self._stat_bump("capability.call.unresolved")
    return ToolExecResult(result=f"未找到能力「{capability_name}」")
self._stat_bump("capability.call.resolved")
```

> 两处都是"bump attempt 一次 → 按 `target` 真值 bump 恰好一个 resolved/unresolved"，结构上保证 `attempt == resolved + unresolved`。`_stat_bump` 已受 `dashboard_enabled` 控制且吞异常（R5.5）。

## Data Models

### 能力字典新增字段 `when_to_use`（可选）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `when_to_use` | `str` | 缺省（键不存在） | Layer 3 合成产出的"何时使用"触发描述。Layer 2 Match_Text 优先取它，缺失/空回退 `description`。最长截断 300 字符。其余既有字段语义不变（R6.2）。 |

`personal_capabilities.json` 顶层结构不变（`version` / `capabilities` / `last_research_ts` / 既有 `migrated_*` 标记）。新增字段为加法，旧文件可直接读写（R6.1）。

### 进程内状态 `_promoted_cap_ids`

| 名称 | 类型 | 生命周期 | 说明 |
|------|------|----------|------|
| `self._promoted_cap_ids` | `set[str]` | 进程内（重启清空） | 记录本进程已晋升过的能力 `id`，供 Trial_Slot 判定"从未被晋升过的新能力"。在 `__init__` 初始化为 `set()`。不持久化（决策 3）。 |

### 能力工具带（Capability_Tool_Belt）

非独立持久结构，是 `context.get_llm_tool_manager().func_list` 中由晋升注册的 `DynamicCapabilityTool` 子集的逻辑视图。大小受 `capability_promote_top_k` 与 `dynamic_tool_daily_quota` 约束（R1.7、R5/Property 5）。

### 度量计数 key（写入 stats_daily.counts）

| key | 触发点 |
|-----|--------|
| `capability.promoted` | `_refresh_capability_tool_belt` 每次真实新注册 |
| `capability.match.hint_injected` | `on_llm_request` 追加一条 Relevance_Hint |
| `capability.call.attempt` | dispatcher `call` / `_execute_single_capability` 入口 |
| `capability.call.resolved` | `_resolve_capability` 命中 |
| `capability.call.unresolved` | `_resolve_capability` 未命中 |

### 配置项新增（`_conf_schema.json`）

| key | 类型 | 默认 | hint 标注 |
|-----|------|------|-----------|
| `capability_promote_enabled` | bool | `false` | 🔴 高 token（注入更多命名工具→主请求工具列表变长）。文档推荐开启以闭合使用闭环 |
| `capability_promote_top_k` | int | `3` | ⚪ Token 无。晋升为命名工具的能力数上限 |
| `capability_match_hint_enabled` | bool | `true` | 🟢 近乎免费（本地 Jaccard，仅命中时多注入一句） |
| `capability_match_hint_threshold` | float | `0.2` | ⚪ 注入定向提示的最低词法相关性阈值 |
| `capability_match_hint_backend` | string | `"lexical"` | ⚪ `lexical`/`embedding`；embedding 不可用自动降级 Jaccard |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

这些属性面向属性测试（Hypothesis，≥100 迭代，每属性单测试）。属性 1–5 测晋升选择逻辑（纯函数 `_select_promotion_set` + 编排器配额边界），6–8 测相关性（纯函数 `_compute_capability_relevance` / `_build_capability_hint`），9 测度量不变式。其余验收标准为示例/集成/冒烟测试（见 Testing Strategy）。

### Property 1: 晋升 Top-K 选择正确性

*对任意* 能力集合与 `K = capability_promote_top_k`，`_select_promotion_set(caps, K, already_promoted_ids)` 返回集合大小 `<= K`，且在不触发 Trial_Slot 替换的情况下，晋升集合中任一能力的 Value_Score 不低于未晋升能力中的最大 Value_Score（严格按价值分降序取 Top-K）。

**Validates: Requirements 1.3, 1.7**

### Property 2: 晋升不依赖自封置信度（解死锁）

*对任意* 两条 `usage_count` / `corrections` / `last_updated` 相同而 `confidence` 不同的能力，二者在 `_select_promotion_set` 中的晋升资格相同；且价值分排在 Top-K 内的低 `confidence`（含 `0.3` 基线）能力会被纳入晋升集合，仅靠高 `confidence` 而价值分不在 Top-K 的能力不会被晋升。

**Validates: Requirements 1.4, 2.1**

### Property 3: Trial_Slot 保证新能力可见

*对任意* 同时包含"高价值老能力"与"至少一个 `usage_count==0` 且 `id` 不在 `already_promoted_ids` 的新能力"的集合，当 `K >= 1` 时，`_select_promotion_set` 的返回集合中至少包含一个这样的新能力（占用 Trial_Slot）。

**Validates: Requirements 1.5**

### Property 4: 晋升默认关无回归

*对任意* 能力集合，当 `capability_promote_enabled=false` 时，调用 `_refresh_capability_tool_belt` 因晋升而新注册的 Named_Tool 数为 `0`（注册行为退化为 v0.9.4 既有逻辑）。

**Validates: Requirements 2.1, 6.3**

### Property 5: 晋升受配额上界约束

*对任意* 能力集合与当日已用配额，调用 `_refresh_capability_tool_belt` 本次新注册的 Named_Tool 数 `<= min(K, 当日剩余 dynamic_tool_daily_quota)`，且晋升集合（能力工具带候选）大小 `<= K`。

**Validates: Requirements 1.6, 1.7**

### Property 6: Layer 2 命中即注入、不命中不注入

*对任意* 用户消息与非空能力集合，当且仅当最高 Lexical_Relevance `>= threshold` 时，`_build_capability_hint` 返回非空提示，且该提示包含相关性最高（argmax）能力的名称；当最高相关性 `< threshold` 时返回空串 `""`。`_compute_capability_relevance` 返回的 `best_index` 落在合法范围内、`best_score` 为有限非负值。

**Validates: Requirements 3.4, 3.5, 3.6**

### Property 7: Layer 2 后端降级不抛异常

*对任意* 输入，当 `backend="embedding"` 且 `embed_fn` 为 `None` 或调用时抛异常时，`_compute_capability_relevance` 降级为 Jaccard，返回有限非负分值，绝不抛出异常（且降级结果等于 lexical 路径结果）。

**Validates: Requirements 3.7**

### Property 8: Layer 3 Match_Text 回退

*对任意* 能力，参与 Layer 2 计算的 Match_Text 等于：当 `when_to_use` 存在且非空时取 `when_to_use`，否则取 `description`；缺失 `when_to_use` 的能力其相关性计算返回有限非负值且不报错。

**Validates: Requirements 4.3, 4.4**

### Property 9: 调用埋点互斥穷尽

*对任意* 一串能力调用序列（可解析名与不可解析名混合），按"先 bump `capability.call.attempt`，再依 `_resolve_capability` 结果 bump 恰好一个 `resolved`/`unresolved`"的模式累加后，`capability.call.attempt` 的累加值恒等于 `capability.call.resolved` 与 `capability.call.unresolved` 累加值之和（每次尝试被恰好分类一次）。

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

## Error Handling

| 场景 | 处理策略 | 影响范围 | 对应需求 |
|------|----------|----------|----------|
| `_refresh_capability_tool_belt` 内任意步骤抛异常（读盘、选择、注册） | 整体 `try/except` 吞掉，`logger.debug` 记录，方法正常返回 | 不影响 `initialize()` / 对话 / 健康维护 | R2.4 |
| `capability_system_enabled=false` | 刷新方法首行 return，零动作 | 无晋升/注册/刷新 | R2.2 |
| `capability_promote_enabled=false` | 刷新方法 gate return | 零新注册（退化 v0.9.4） | R2.1, Property 4 |
| 晋升命中已注册同名工具 | 复用 `_dynamically_register_capability_as_tool` 既有同名跳过 | 不重复注册 | R2.3 |
| 当日配额耗尽 | `_dynamically_register_capability_as_tool` 既有配额检查，能力仅入库不注册 | 新注册数 `<= 剩余配额` | R1.6, Property 5 |
| Layer 2 相关性计算 / 提示注入异常 | `on_llm_request` 内 `try/except` 吞掉，`logger.debug` | 不影响系统提示构建与对话 | R3 系列 |
| `backend="embedding"` 但 `embed_fn` 缺失/抛异常 | `_compute_capability_relevance` 内 `try/except` 降级 Jaccard | 返回有限非负分，不抛 | R3.7, Property 7 |
| 能力缺 `when_to_use` | Match_Text 回退 `description`（`(when_to_use or "").strip() or description`） | 匹配/注入正常 | R4.3, R4.4, Property 8 |
| `_stat_bump` 埋点失败或 `dashboard_enabled=false` | 复用既有 `_stat_bump`（吞异常、关则跳过累加） | 不影响主流程 | R5.5 |
| `_select_promotion_set` 收到 `K<=0` 或空能力集 | 返回 `[]` | 无晋升 | 防御性 |

## Testing Strategy

### 双轨方法

- **属性测试（Hypothesis）**：覆盖纯函数的普遍性质，每条测试单一属性、`max_examples >= 100`、注释 `# Feature: capability-loop-strengthening, Property N: ...`。
- **示例/集成测试**：覆盖接线（`on_llm_request` 注入、`initialize()`/健康维护调用、dispatcher 埋点、合成提示字段、schema 默认值），每项 1–3 个代表性示例（R7.5：不对纯接线做 100 次迭代）。
- 沿用 `tests/_cap_host.py` 的 `types.ModuleType` 桩 + 最小宿主类约定，不依赖真实 `astrbot.*` 运行时（R7.4）。

### PBT 适用性说明

晋升选择（`_select_promotion_set`）、相关性计算（`_compute_capability_relevance` / `_build_capability_hint`）是输入空间大、有普遍不变式（大小界、排序、argmax、降级不抛、Match_Text 回退）的纯函数 → 适用 PBT。度量互斥穷尽性是对任意调用序列成立的不变式 → 适用 PBT。晋升配额边界（Property 5）通过给最小宿主注入内存 `_daily_tool_register` 计数与一个假 `add_llm_tools` 来测，避免真实框架调用。

### 属性测试（≥100 迭代，每属性单测试）

| 属性 | 被测纯函数 | 生成器要点 | 建议文件 |
|------|-----------|-----------|----------|
| Property 1 | `_select_promotion_set` | 随机能力列表（含 id/usage/corrections/last_updated）、随机 K | `test_v0910_prop1_topk.py` |
| Property 2 | `_select_promotion_set` | 成对能力仅 confidence 不同；含低 conf 高 value 项 | `test_v0910_prop2_no_confidence.py` |
| Property 3 | `_select_promotion_set` | 集合含 ≥1 新能力（usage==0, id∉already_promoted）+ 高价值老能力 | `test_v0910_prop3_trial_slot.py` |
| Property 4 | `_refresh_capability_tool_belt`（promote 关） | 任意能力集合 + 假注册计数 | `test_v0910_prop4_promote_off.py` |
| Property 5 | `_refresh_capability_tool_belt`（promote 开） | 任意能力集合 + 随机已用配额/K | `test_v0910_prop5_quota_bound.py` |
| Property 6 | `_build_capability_hint` / `_compute_capability_relevance` | 随机 user_text + 能力集合 + 随机 threshold | `test_v0910_prop6_hint_hit.py` |
| Property 7 | `_compute_capability_relevance` | 任意输入 + `embed_fn ∈ {None, 抛异常}` | `test_v0910_prop7_embed_downgrade.py` |
| Property 8 | `_compute_capability_relevance` | 能力含/缺 when_to_use（空串/缺键/非空） | `test_v0910_prop8_match_text.py` |
| Property 9 | 埋点累加模式（最小 stat 宿主） | 随机 (name, 可解析?) 调用序列 | `test_v0910_prop9_metrics.py` |

### 示例 / 集成 / 冒烟测试

- **Schema 默认值（SMOKE）**：`_conf_schema.json` 含 5 个新 key 及正确默认（promote=false 高 token 标注、hint=true、top_k=3、threshold=0.2、backend="lexical"）。覆盖 R1.1、R1.2、R2.5、R3.1–3.3、R6.4、R7.2/7.3/7.4/7.5。
- **晋升接线（EXAMPLE）**：`initialize()` 与 `_maintain_capabilities_health()` 末尾调用 `_refresh_capability_tool_belt`（R1.3 wiring）；`capability.promoted` 在一次新注册时累加一次（R1.8）；`capability_system_enabled=false` → no-op（R2.2）；同名跳过不双注册（R2.3）；注册抛异常被吞（R2.4）。
- **Layer 2 接线（EXAMPLE）**：保证命中的能力 → `on_llm_request` 路径追加提示并 bump `capability.match.hint_injected`（R3.8）；`capability_match_hint_enabled=false` → 注入文本不变、无额外计算/计数（R3.9）。
- **Layer 3（EXAMPLE）**：`danger.py` 两处合成提示模板含 `when_to_use`（R4.1）；`_create_or_update_capability` 透传并持久化 `when_to_use`（R4.2）；存量无字段能力可创建/注入（R4.4、R6.1、R6.2）。
- **度量 gate（SMOKE）**：`dashboard_enabled=false` → 计数不增且不抛（R5.5，复用既有 `_stat_bump` 行为）。
- **回归（INTEGRATION）**：改动前全部 310 个测试通过（R7.1）。`_dynamically_register_capability_as_tool` 的 `force` 默认 `False`，既有调用方与既有测试行为不变；`_create_or_update_capability` 的 0.65 自动注册路径保持原样。

### 运行

```
python -m pytest -q
```

> 长时间运行的命令请在你的终端手动执行。属性测试默认 `@settings(max_examples=100)`。
