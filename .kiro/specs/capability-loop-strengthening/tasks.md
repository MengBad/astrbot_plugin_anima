# Implementation Plan: capability-loop-strengthening (Anima v0.9.10)

## Overview

闭合个人能力系统的使用闭环：三层（晋升 / 定向提示 / when_to_use）+ 一条度量闭环。实现遵循 Anima 既有约定 —— 纯逻辑先行（`_select_promotion_set` / `_compute_capability_relevance` / `_build_capability_hint`），再薄编排器，最后接线到 `initialize()` / `_maintain_capabilities_health()` / `on_llm_request` / dispatcher。

整体改动是**加法且默认安全**：`capability_promote_enabled` 默认 `false`，关闭时行为与 v0.9.4 完全一致（零回归）。所有新方法落在 `anima/mixins/capabilities.py`（`CapabilitiesMixin`）。测试沿用 `tests/_cap_host.py` 的 `types.ModuleType` 桩 + 最小宿主类；属性测试用 Hypothesis（`max_examples >= 100`，每文件单一属性，注释 `# Feature: capability-loop-strengthening, Property N: ...`）。

实现语言：**Python**（设计文档已采用具体语言，无需另行选择）。

## Tasks

- [x] 1. 配置脚手架与进程内状态
  - [x] 1.1 在 `_conf_schema.json` 新增 5 个配置项
    - `capability_promote_enabled`（bool，默认 `false`，hint 标注 🔴 高 token，描述推荐开启）
    - `capability_promote_top_k`（int，默认 `3`）
    - `capability_match_hint_enabled`（bool，默认 `true`）
    - `capability_match_hint_threshold`（float，默认 `0.2`）
    - `capability_match_hint_backend`（string，默认 `"lexical"`，options `["lexical","embedding"]`）
    - 保持既有 JSON 结构与缩进风格不变
    - _Requirements: 1.1, 1.2, 2.5, 3.1, 3.2, 3.3, 6.4_

  - [x] 1.2 在 `main.py` `__init__` 初始化 `self._promoted_cap_ids: set[str] = set()`
    - 紧邻既有 `self._daily_tool_register` 初始化处添加（进程内、不持久化）
    - 供 Layer 1 Trial_Slot 判定"从未被晋升过的新能力"
    - _Requirements: 1.5_

  - [x]* 1.3 编写 schema 默认值冒烟测试（`tests/test_v0910_smoke_schema.py`）
    - 读取 `_conf_schema.json`，断言 5 个新 key 存在且默认值正确（promote=false 且 hint 含高 token 标注、top_k=3、hint_enabled=true、threshold=0.2、backend="lexical"）
    - _Requirements: 1.1, 1.2, 2.5, 3.1, 3.2, 3.3, 6.4, 7.2, 7.5_

- [x] 2. Layer 1 晋升选择（纯函数）
  - [x] 2.1 在 `capabilities.py` 实现纯函数 `_select_promotion_set(self, capabilities, k, already_promoted_ids=None, now=None)`
    - 仅按 `_capability_value_score(cap, now)` 降序稳定排序（不读 `confidence`）
    - `k <= 0` 或空集合 → 返回 `[]`；返回长度 `<= k`
    - Trial_Slot：若存在 `usage_count==0` 且 `id` 不在 `already_promoted_ids` 的新能力，且 Top-K 中不含任何此类新能力且 `k >= 1`，则取 Top-K 前 `k-1` 个并追加价值分最高的新能力
    - 无 I/O、无 LLM、无 config 读取；`now` 可注入以保证确定性
    - _Requirements: 1.3, 1.4, 1.5, 1.7_

  - [x]* 2.2 编写属性测试（`tests/test_v0910_prop1_topk.py`）
    - **Property 1: 晋升 Top-K 选择正确性**
    - **Validates: Requirements 1.3, 1.7**
    - 随机能力列表（id/usage/corrections/last_updated）+ 随机 K；断言返回大小 `<= K`，且未触发 Trial_Slot 替换时晋升集合内任一能力 Value_Score 不低于未晋升者的最大 Value_Score

  - [x]* 2.3 编写属性测试（`tests/test_v0910_prop2_no_confidence.py`）
    - **Property 2: 晋升不依赖自封置信度（解死锁）**
    - **Validates: Requirements 1.4, 2.1**
    - 成对能力仅 `confidence` 不同（其余 usage/corrections/last_updated 相同）→ 晋升资格相同；低 conf 但价值分在 Top-K 内者被纳入

  - [x]* 2.4 编写属性测试（`tests/test_v0910_prop3_trial_slot.py`）
    - **Property 3: Trial_Slot 保证新能力可见**
    - **Validates: Requirements 1.5**
    - 集合含 ≥1 新能力（`usage_count==0` 且 `id ∉ already_promoted_ids`）+ 高价值老能力；`K >= 1` 时返回集合至少含一个该类新能力

- [x] 3. Layer 1 注册小重构与编排器
  - [x] 3.1 给 `_dynamically_register_capability_as_tool` 增加可选参数 `force: bool = False`
    - `force=False`（默认）：行为完全不变，既有 `dynamic_tool_registration_enabled` 与 `register_as_independent_tool` 两个标记闸门照常生效
    - `force=True`：跳过上述两个标记闸门，但**保留**每日配额检查与同名跳过
    - 既有调用方（`_create_or_update_capability` 内）不传 `force`，行为零变化
    - _Requirements: 2.1, 2.3, 6.2, 7.1_

  - [x] 3.2 在 `capabilities.py` 实现编排器 `_refresh_capability_tool_belt(self)`
    - 整体 `try/except` 包裹，异常仅 `logger.debug`，不影响主流程
    - 首行 gate：`capability_system_enabled=false` → return；`capability_promote_enabled=false` → return
    - 读能力 → `k=int(config.capability_promote_top_k)` → `selected=self._select_promotion_set(caps, k, self._promoted_cap_ids)`
    - 对每个 selected：比较 `self._daily_tool_register["count"]` 前后差值，以 `force=True` 调注册；仅真正新注册时把 `id` 加入 `self._promoted_cap_ids` 并 `self._stat_bump("capability.promoted")`
    - _Requirements: 1.3, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 把 `_refresh_capability_tool_belt()` 接线进两个调用点
    - `main.py` `initialize()`：在 `_migrate_capabilities_v094()` 之后（try/except 内）追加调用
    - `capabilities.py` `_maintain_capabilities_health()`：方法末尾追加调用
    - _Requirements: 1.3_

  - [x]* 3.4 编写属性测试（`tests/test_v0910_prop4_promote_off.py`）
    - **Property 4: 晋升默认关无回归**
    - **Validates: Requirements 2.1, 6.3**
    - 任意能力集合 + 假注册计数；`capability_promote_enabled=false` 时 `_refresh_capability_tool_belt` 因晋升而新注册的 Named_Tool 数为 0

  - [x]* 3.5 编写属性测试（`tests/test_v0910_prop5_quota_bound.py`）
    - **Property 5: 晋升受配额上界约束**
    - **Validates: Requirements 1.6, 1.7**
    - 给最小宿主注入内存 `_daily_tool_register` 计数与假 `add_llm_tools`；任意能力集合 + 随机已用配额/K；新注册数 `<= min(K, 当日剩余配额)`，且晋升候选集合大小 `<= K`

  - [x]* 3.6 编写晋升接线示例测试（`tests/test_v0910_promotion_wiring.py`）
    - 1–3 个代表性示例：一次真实新注册使 `capability.promoted` +1（R1.8）；`capability_system_enabled=false` → no-op（R2.2）；同名已注册 → 不重复注册（R2.3）；注册抛异常被吞、主流程继续（R2.4）
    - _Requirements: 1.8, 2.2, 2.3, 2.4_

- [x] 4. Layer 2 相关性（纯函数）
  - [x] 4.1 在 `capabilities.py` 实现纯函数 `_compute_capability_relevance(self, user_text, capabilities, *, backend="lexical", embed_fn=None) -> tuple[int, float]`
    - Match_Text = `(cap.get("when_to_use") or "").strip() or cap.get("description","")`
    - lexical：`from ..similarity import text_jaccard`
    - `backend=="embedding"` 且 `embed_fn` 提供：用注入的 `embed_fn`；`embed_fn` 缺失或抛异常 → `try/except` 降级 `text_jaccard`，绝不抛异常
    - 空能力集 → `(-1, 0.0)`；`best_score` 有限非负
    - _Requirements: 3.4, 3.7, 4.3, 4.4_

  - [x] 4.2 在 `capabilities.py` 实现纯函数 `_build_capability_hint(self, user_text, capabilities, threshold, *, backend="lexical", embed_fn=None) -> str`
    - 调 `_compute_capability_relevance`；`idx < 0` 或 `score < threshold` → 返回 `""`
    - 命中则返回指向 argmax 能力名称的定向提示串；threshold 由编排器传入（比较逻辑保持纯）
    - _Requirements: 3.5, 3.6_

  - [x]* 4.3 编写属性测试（`tests/test_v0910_prop6_hint_hit.py`）
    - **Property 6: Layer 2 命中即注入、不命中不注入**
    - **Validates: Requirements 3.4, 3.5, 3.6**
    - 随机 user_text + 非空能力集合 + 随机 threshold；当且仅当最高相关性 `>= threshold` 时 `_build_capability_hint` 返回非空且含 argmax 能力名；否则返回 `""`；`best_index` 合法、`best_score` 有限非负

  - [x]* 4.4 编写属性测试（`tests/test_v0910_prop7_embed_downgrade.py`）
    - **Property 7: Layer 2 后端降级不抛异常**
    - **Validates: Requirements 3.7**
    - 任意输入 + `embed_fn ∈ {None, 抛异常的 fn}` 且 `backend="embedding"`；降级为 Jaccard、返回有限非负、绝不抛，且结果等于 lexical 路径

  - [x]* 4.5 编写属性测试（`tests/test_v0910_prop8_match_text.py`）
    - **Property 8: Layer 3 Match_Text 回退**
    - **Validates: Requirements 4.3, 4.4**
    - 能力含/缺 `when_to_use`（非空/空串/缺键）；Match_Text 等于 when_to_use 非空时取之否则取 description；缺字段能力相关性计算返回有限非负且不报错

- [x] 5. Layer 2 接线进 on_llm_request
  - [x] 5.1 在 `main.py` `on_llm_request`（`caps_injection` 注入之后）接线定向提示
    - gate `capability_match_hint_enabled`（默认 true，关则跳过、不计算不计数）
    - 读能力 + `user_text=event.message_str` + `threshold=float(config.capability_match_hint_threshold)` + `backend=config.capability_match_hint_backend`
    - 调 `_build_capability_hint(..., embed_fn=None)`；命中则 append 到 `injection_parts` 并 `self._stat_bump("capability.match.hint_injected")`
    - 整段 `try/except` 吞异常（`logger.debug`）
    - _Requirements: 3.5, 3.8, 3.9_

  - [x]* 5.2 编写 Layer 2 接线示例测试（`tests/test_v0910_layer2_wiring.py`）
    - 1–3 个代表性示例：命中能力 → 注入提示并 bump `capability.match.hint_injected`（R3.8）；`capability_match_hint_enabled=false` → 注入文本不变、无额外计算/计数（R3.9）
    - _Requirements: 3.8, 3.9_

- [x] 6. Layer 3 合成时要求 when_to_use
  - [x] 6.1 在 `danger.py` 两处合成路径加入 `when_to_use`
    - 两处合成 prompt 的 JSON 模板新增 `"when_to_use"` 字段（描述适用的具体触发场景）
    - 两处 `cap_payload` 透传：`if "when_to_use" in cap_data: cap_payload["when_to_use"] = str(cap_data["when_to_use"])[:300]`
    - 确认 `_create_or_update_capability` 更新分支排除列表（仅 `corrections`/`usage_count`）与新建分支均不剥离 `when_to_use`，使其自动持久化
    - _Requirements: 4.1, 4.2_

  - [x]* 6.2 编写 Layer 3 示例测试（`tests/test_v0910_layer3_when_to_use.py`）
    - 1–3 个代表性示例：合成 prompt 模板含 `when_to_use`（R4.1）；`_create_or_update_capability` 透传并持久化 `when_to_use`（R4.2）；缺 `when_to_use` 的存量能力可正常创建/注入（R4.4、R6.1、R6.2）
    - _Requirements: 4.1, 4.2, 4.4, 6.1, 6.2_

- [x] 7. 度量闭环接线
  - [x] 7.1 在 `main.py` dispatcher `call`（`AnimaPersonalCapabilityDispatcher`）接线调用埋点
    - 解析前 `plugin._stat_bump("capability.call.attempt")`
    - `_resolve_capability` 返回空 → `plugin._stat_bump("capability.call.unresolved")` 后返回未找到结果
    - 命中 → `plugin._stat_bump("capability.call.resolved")`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 7.2 在 `capabilities.py` `_execute_single_capability`（Named_Tool 路径）接线调用埋点
    - 同一模式：先 `self._stat_bump("capability.call.attempt")`，再依 `_resolve_capability` 结果 bump 恰好一个 `resolved`/`unresolved`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x]* 7.3 编写属性测试（`tests/test_v0910_prop9_metrics.py`）
    - **Property 9: 调用埋点互斥穷尽**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - 随机 (name, 可解析?) 调用序列，最小 stat 宿主累加后断言 `attempt == resolved + unresolved`（每次尝试被恰好分类一次）

  - [x]* 7.4 编写度量 gate 示例测试（`tests/test_v0910_metrics_wiring.py`）
    - 1–3 个代表性示例：`dashboard_enabled=false` → 计数不增且不抛异常（R5.5，复用既有 `_stat_bump` 行为）
    - _Requirements: 5.5_

- [x] 8. 检查点 - 全量回归
  - 运行 `python -m pytest -q`，确保改动前 310 个既有测试 + 本特性新增测试全部通过；有问题先修复再继续。Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 7.1_

- [x] 9. 版本号与文档
  - [x] 9.1 版本号 bump 到 `0.9.10`
    - `metadata.yaml` 的 `version: "0.9.10"`
    - `main.py` `@register(...)` 第 4 个参数 `"0.9.10"`
    - _Requirements: 6.4_

  - [x] 9.2 更新 CHANGELOG 与 README
    - CHANGELOG 顶部新增 0.9.10 条目（晋升 / 定向提示 / when_to_use / 度量闭环）
    - README：版本徽章改 0.9.10，新增能力系统强化说明、新命令/配置文档，并明确推荐开启 `capability_promote_enabled`
    - _Requirements: 2.5_

- [x] 10. 最终检查点 - 全量回归
  - 再次运行 `python -m pytest -q`，确认版本/文档改动后全部测试仍通过。Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 7.1_

## Notes

- 标记 `*` 的子任务为可选测试任务（强烈推荐），可为更快 MVP 跳过；核心实现子任务从不标 `*`。
- 每个任务引用具体需求条款以保证可追溯。
- 属性测试覆盖纯函数普遍不变式（≥100 迭代、单一属性）；示例/集成测试覆盖接线点（1–3 个代表性示例，避免对纯接线做 100 次迭代）。
- 检查点确保增量验证；纯逻辑先行 → 编排器 → 接线 → 文档，避免悬空未集成代码。
- 全程默认安全：`capability_promote_enabled=false` 时行为与 v0.9.4 完全一致。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1"] },
    { "id": 1, "tasks": ["1.3", "2.2", "2.3", "2.4", "3.1"] },
    { "id": 2, "tasks": ["3.2"] },
    { "id": 3, "tasks": ["3.3"] },
    { "id": 4, "tasks": ["3.4", "3.5", "3.6", "4.1"] },
    { "id": 5, "tasks": ["4.2"] },
    { "id": 6, "tasks": ["4.3", "4.4", "4.5", "5.1", "6.1", "7.2"] },
    { "id": 7, "tasks": ["5.2", "6.2", "7.1"] },
    { "id": 8, "tasks": ["7.3", "7.4", "9.1"] },
    { "id": 9, "tasks": ["9.2"] }
  ]
}
```
