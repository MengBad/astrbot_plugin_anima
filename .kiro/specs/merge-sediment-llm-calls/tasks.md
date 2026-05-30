# Implementation Plan: 合并沉淀流程的三次内部 LLM 调用

## Overview

按"纯逻辑先行、下游统一、最后接线"的顺序增量实现合并评估器。先落地配置项与 `MergedResult` 数据结构，再实现两个可属性测试的纯函数（`Prompt_Assembler` / `Response_Parser`），随后抽出与路径无关的下游统一写入函数并让旧路径复用它，最后实现 `Merged_Evaluator` 编排并在 `_sediment_process` 接入特性开关分支。所有改动默认走旧路径（`sediment_merge_llm_calls=false`），开关关闭即完全恢复 v0.9.1 行为。

实现语言：**Python**（沿用既有 `anima/mixins/` 代码风格与 `tests/` 测试约定）。属性测试使用 **Hypothesis**，每条 Correctness Property 用单个属性测试实现，至少 100 次迭代。

## Tasks

- [x] 1. 配置项与测试基础设施
  - [x] 1.1 在 `_conf_schema.json` 新增 `sediment_merge_llm_calls` 配置项
    - 在 `_conf_schema.json` 中加入 `bool` 类型、`default: false` 的开关，附带省 token 与 A/B 对比说明的 `hint`（计入 `llm.sediment_merged`）
    - _Requirements: 8.1_

  - [x]* 1.2 搭建合并特性测试基础设施与 Hypothesis 依赖
    - 将 `hypothesis` 加入 `requirements.txt`（不自行实现 PBT 框架）
    - 新建 `tests/test_v092_config.py`：沿用 `test_v090_stats.py` 的 `types.ModuleType` 桩掉 `astrbot.*` 约定，构造最小宿主类混入目标 mixin，并验证 `_conf_schema.json` 中存在 `sediment_merge_llm_calls` 且默认 `false`
    - _Requirements: 8.1, 9.1_

- [x] 2. 定义合并结果数据模型
  - [x] 2.1 在 `anima/mixins/sediment.py` 定义 `MergedResult`
    - 用 `@dataclass` 定义 `emotion_score: float = 0.0`、`relationships: Optional[dict] = None`、`desire: Optional[str] = None`
    - 字段契约：`emotion_score` 恒在 `[0.0, 1.0]`；`relationships`/`desire` 为 `None` 表示本轮不写入
    - _Requirements: 1.1, 3.4, 3.5_

- [x] 3. 实现提示词组装器 Prompt_Assembler
  - [x] 3.1 实现纯函数 `_build_merged_prompt`
    - 在 `anima/mixins/sediment.py` 实现 `_build_merged_prompt(self, event, response_text, sylanne_state, *, relationship_on, desire_on) -> tuple[str, frozenset[str]]`
    - 情绪分段恒在、`requested` 恒含 `"emotion_score"`；`relationship_on` 为真时加入关系分段与 `"relationships"`；`desire_on`（由调用方按 `desire_enabled` 且非空 `sylanne_state` 计算）为真时加入欲望分段与 `"desire"`
    - 提示词明确要求"只返回一个 JSON 对象，不要任何额外文字"，并按 `requested` 动态列出字段说明与 JSON 骨架；关系与欲望均省略时退化为纯情绪评估语义
    - 保持纯函数（不读配置、不读文件、不调用 LLM）
    - _Requirements: 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 3.2 Write property test for prompt assembly
    - 新建 `tests/test_v092_prop2_prompt.py`
    - **Property 2: 提示词与请求字段的条件化组装**
    - **Validates: Requirements 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**
    - 生成器：三布尔开关组合 × `sylanne_state`（空/纯空白/非空）；断言 `requested` 双条件成立、退化纯情绪时 `requested == {"emotion_score"}` 且提示词不提及关系/欲望
    - 注释标签：`# Feature: merge-sediment-llm-calls, Property 2: ...`

- [x] 4. 实现响应解析器 Response_Parser
  - [x] 4.1 实现纯函数 `_parse_merged_response`
    - 在 `anima/mixins/sediment.py` 实现 `_parse_merged_response(self, text, requested) -> MergedResult`
    - 先用与 `_danger_relationship_inference` 一致的正则剥 Markdown 围栏再 `json.loads`
    - 解析成功：`emotion_score` 数字钳制到 `[0.0,1.0]`，缺失/非数字则 `0.0`；`relationships` 仅当 `"relationships" in requested` 且为非空 dict 时填入，否则 `None`；`desire` 仅当 `"desire" in requested` 时取字符串（`null` 视为无）
    - 解析失败：正则提取首个 0–1 数字（钳制）作情绪分，提不到则 `0.0`，两种情形 `relationships`/`desire` 均为 `None`
    - 不触发任何 LLM 调用，不回退旧路径
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 4.2 Write property test for successful parse round-trip
    - 新建 `tests/test_v092_prop3_parse_success.py`
    - **Property 3: 成功解析的围栏剥离、钳制与往返**
    - **Validates: Requirements 3.1, 3.2, 3.5**
    - 生成器：任意结果对象编码为 JSON × 围栏变体（无围栏/```` ```json ````/```` ``` ````）× 越界/缺失情绪分；断言情绪分等于 `clamp(value,0,1)` 且 `relationships`/`desire` 正确还原

  - [x]* 4.3 Write property test for invalid-JSON downgrade
    - 新建 `tests/test_v092_prop4_parse_downgrade.py`
    - **Property 4: 非法 JSON 的降级提取**
    - **Validates: Requirements 3.3, 3.4**
    - 生成器：无法 JSON 解析的噪声文本（含/不含可提取 0–1 数字）；断言取首个 0–1 数字或兜底 `0.0`，且 `relationships`/`desire` 均为 `None`

- [x] 5. 实现下游统一写入函数
  - [x] 5.1 实现 `_apply_relationships_from_map`
    - 在 `anima/mixins/sediment.py` 实现关系映射写入：入参非 `dict`/为空时静默返回；命中 `_is_rejected` 丢弃整个映射；否则 `_read_worldview` → 确保 `relationships` 存在 → `update` → 超 30 条保留最近 30 → `_write_worldview`；任何情形不抛异常
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x]* 5.2 Write property test for worldview relationship write & cap
    - 新建 `tests/test_v092_prop6_relationships.py`
    - **Property 6: 世界观关系写入与上限不变量**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - 生成器：既有 dict × 候选映射（含 `None`/非 dict/空 dict/命中拒答/超 30 条）；断言不变或 `update` 后 `len <= 30`，且不抛异常

  - [x] 5.3 实现 `_apply_desire_from_text`
    - 在 `anima/mixins/sediment.py` 实现欲望写入：退化值（`None`/空串/`"无"`/长度 ≤ 2）不创建；命中 `_is_rejected` 丢弃；队列已达 `desire_max_queue` 不写；`_is_desire_already_expressed` 为真跳过；通过则追加欲望字典（`source="relationship"`、`kind="outward"`、`intensity=0.7`、`satisfied=False` 等，字段同旧 `_maybe_generate_desire`）并 `_stat_bump("desire.created.outward")`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.3_

  - [x]* 5.4 Write property test for desire write filtering & dict shape
    - 新建 `tests/test_v092_prop7_desire.py`
    - **Property 7: 欲望写入的过滤与字典形态**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 7.3**
    - 生成器：候选文本（含退化值）× 队列长度 × 去重判定结果；断言全条件满足时恰写一条且恰触发一次 `desire.created.outward`、字典字段恒为约定形态，任一不满足则不写不计数

- [x] 6. Checkpoint - 纯逻辑与下游测试
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. 旧路径重构复用统一下游写入
  - [x] 7.1 重构 `_danger_relationship_inference` 复用 `_apply_relationships_from_map`
    - 在 `anima/mixins/danger.py` 改为"取得文本 → 解析 relations → 调用 `_apply_relationships_from_map`"，保留自身 LLM 调用与 `_stat_bump("llm.relation")` 不变
    - _Requirements: 7.4, 8.3_

  - [x] 7.2 重构 `_maybe_generate_desire` 复用 `_apply_desire_from_text`
    - 在 `anima/mixins/desire.py` 改为取得 `result` 文本后调用 `_apply_desire_from_text`，保留自身 LLM 调用、前置开关与既有埋点行为不变
    - _Requirements: 7.4, 8.3_

  - [x]* 7.3 Write regression tests for refactored legacy path
    - 新建 `tests/test_v092_legacy_path.py`
    - 验证开关关闭时旧路径三次分离调用与既有埋点（`llm.emotion`/`llm.relation`/`desire.created.outward`）行为不变，且重构后外部行为与重构前一致
    - _Requirements: 7.4, 8.3, 9.5_

- [x] 8. 实现合并评估器 Merged_Evaluator
  - [x] 8.1 实现 `_merged_evaluate` 编排
    - 在 `anima/mixins/sediment.py` 实现 `async _merged_evaluate(self, event, response_text, sylanne_state) -> MergedResult`
    - 流程：计算 `relationship_on`/`desire_on` 布尔 → `_build_merged_prompt` → `await _get_provider_id`（空串返回 `MergedResult(0.0,None,None)` 且不发起调用）→ `asyncio.wait_for(llm_generate(...), timeout=15.0)`（`TimeoutError` 返回安全结果且不计数）→ 仅在实际完成物理调用后 `_stat_bump("llm.sediment_merged")` → `_parse_merged_response`
    - 任意失败路径返回安全 `MergedResult`，绝不抛异常、绝不回退旧三次调用
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 7.1_

  - [x]* 8.2 Write property test for single physical-call discipline
    - 新建 `tests/test_v092_prop1_single_call.py`
    - **Property 1: 单次物理调用纪律**
    - **Validates: Requirements 1.1, 1.3, 1.5, 3.6, 7.1, 7.2**
    - 生成器：开关组合 × {正常响应, 超时, 空 provider}；用可计数异步 mock 注入 `llm_generate`，断言至多一次物理调用、当且仅当完成时触发一次 `llm.sediment_merged`、永不触发 `llm.emotion`/`llm.relation`、空 provider/超时返回安全结果且不发起调用

- [x] 9. 接入 `_sediment_process` 路径切换与下游接线
  - [x] 9.1 在 `_sediment_process` 增加合并/旧路径分支
    - 在 `anima/mixins/sediment.py` 按 `config.get("sediment_merge_llm_calls", False)` 分支：合并路径在情绪评估处读取 `sylanne_state` 并调用 `_merged_evaluate`，取 `emotion_score` 交既有伤痕放大与 `last_emotion_score` 持久化与阈值门控；过闸后在原下游位置调用 `_apply_relationships_from_map` 与 `_apply_desire_from_text`；合并路径下后段不再发起 `_danger_relationship_inference`/`_maybe_generate_desire` 的 LLM 部分；旧路径保持现状
    - _Requirements: 1.1, 4.1, 4.2, 4.3, 4.4, 7.2, 8.2, 8.3_

  - [x]* 9.2 Write property test for emotion threshold gate
    - 新建 `tests/test_v092_prop5_gate.py`
    - **Property 5: 情绪阈值门控**
    - **Validates: Requirements 4.3**
    - 生成器：任意经伤痕放大后的 `score`（< / ≥ `emotion_threshold`）；断言低于阈值时触发一次 `sediment.skip_low` 并提前返回、无任何关系/欲望写入

  - [x]* 9.3 Write routing & wiring example tests
    - 新建 `tests/test_v092_routing.py`
    - 覆盖开关 true/false 路由（8.2/8.3）、`_get_provider_id` 接线（1.2）、15s 超时参数（1.4）、伤痕放大与高情绪 `_add_scar` 衔接（4.1/4.4）、`dashboard_enabled` 关闭跳过累加（7.5）
    - _Requirements: 1.2, 1.4, 4.1, 4.4, 7.5, 8.2, 8.3_

- [x] 10. 路径等价验证
  - [x]* 10.1 Write property test for legacy/merged downstream equivalence
    - 新建 `tests/test_v092_prop8_equivalence.py`
    - **Property 8: 新旧路径下游等价**
    - **Validates: Requirements 8.4**
    - 生成器：任意 `(emotion_score, relationships, desire)` 三元组；用相同三元组分别驱动旧路径与合并路径，断言 `last_emotion_score`、`worldview.relationships`、欲望队列写入结果一致，差异仅限物理调用次数与统计项（`llm.sediment_merged` vs `llm.emotion`+`llm.relation`）

- [x] 11. Final checkpoint - 全量回归
  - Ensure all tests pass, ask the user if questions arise.（含既有 190 个测试在默认 `sediment_merge_llm_calls=false` 下全绿，_Requirements: 9.1_）

## Notes

- 标记 `*` 的子任务为可选（属性测试 / 单元测试 / 集成测试 / 回归示例测试），可为更快的 MVP 跳过，但本特性触及核心沉淀链、风险最高，强烈建议全部执行。
- 每个任务都引用了具体的需求子条款以保证可追溯。
- Checkpoint 任务用于增量验证；属性测试验证全称正确性属性，单元/示例测试验证具体路由与边界。
- 属性测试统一使用 Hypothesis，每条属性用单个测试实现、至少 100 次迭代，并以 `# Feature: merge-sediment-llm-calls, Property {number}: {property_text}` 注释标注。
- 所有失败路径均不得重新发起旧路径三次分离调用（需求 3.6），确保 token 节省不被降级反噬。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "7.1", "7.2", "8.1"] },
    { "id": 6, "tasks": ["7.3", "8.2", "9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "10.1"] }
  ]
}
```
