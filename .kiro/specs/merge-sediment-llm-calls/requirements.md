# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.2）旨在把沉淀流程（`_sediment_process`，位于 `anima/mixins/sediment.py`）中当前**串行发起的三次独立内部 LLM 调用**合并为**一次结构化 JSON 调用**，以节省约 2/3 的内部调用 token 成本。

当前三个调用点分别是：

1. `_evaluate_emotion`（`anima/mixins/emotion.py`）——输出单个 0–1 浮点情绪强度分。仅受插件总开关 `enabled` 约束，每轮都跑。埋点 `_stat_bump("llm.emotion")`。
2. `_danger_relationship_inference`（`anima/mixins/danger.py`）——输出 JSON 关系映射 `{"uid1 -> uid2": "关系描述"}`，合并进 `worldview.json` 的 `relationships`（上限 30 条）。受 `danger_relationship_inference` 且 `worldview_enabled` 共同约束。埋点 `_stat_bump("llm.relation")`。
3. `_maybe_generate_desire`（`anima/mixins/desire.py`）——输出一句欲望描述或"无"。受 `desire_enabled` 约束，且依赖非空 `sylanne_state`。下游有 `_is_rejected`、`_is_desire_already_expressed` 过滤，写入 `kind="outward"`、`source="relationship"` 的欲望字典。埋点 `_stat_bump("desire.created.outward")`。

合并后必须保持三个子任务各自的开关与前置条件语义不变，下游消费者行为不变，并通过特性开关支持新旧路径切换以降低上线风险。该改动触及核心沉淀链，是本项目目前**风险最高**的一次改动，因此需要明确的回归安全准则。

本文档定义合并调用的行为契约、条件化提示词组装、结构化输出、解析失败降级策略、向后兼容、统计可观测性、以及回归安全要求。

## Glossary

- **Anima**：本插件系统整体，即宿主类 `AnimaPlugin` 及其各 mixin。
- **沉淀流程 (Sediment_Process)**：`_sediment_process` 方法实现的核心处理链：评估情绪 → 检索记忆 → 生成独白 → 存储 → 世界观/欲望/高危功能等后续步骤。
- **内部 LLM 调用 (Internal_LLM_Call)**：Anima 为自身认知机制（情绪评估、关系推断、欲望生成、独白、世界观等）发起的、不直接面向用户回复的 LLM 调用，统一经 `_get_provider_id` 解析模型并优先使用 `internal_provider_id` 配置。
- **合并评估器 (Merged_Evaluator)**：本特性新增的组件，负责用一次结构化 JSON 内部 LLM 调用，同时产出情绪分、关系映射与欲望三类结果。
- **提示词组装器 (Prompt_Assembler)**：合并评估器内部负责按各子任务开关与前置条件条件化拼装提示词分段与请求字段的逻辑。
- **响应解析器 (Response_Parser)**：合并评估器内部负责把 LLM 返回的 JSON 文本解析为结构化结果、并在失败时执行降级策略的逻辑。
- **情绪分 (emotion_score)**：0–1 浮点数，表示对话回复的情绪强度，是沉淀链总闸（经 `emotion_threshold` 门控决定后续是否继续）。
- **emotion_threshold 门控 (Emotion_Threshold_Gate)**：`_sediment_process` 中 `if score < threshold: return` 的判断逻辑，情绪分低于配置 `emotion_threshold`（默认 0.6）时跳过后续整条沉淀链。
- **伤痕放大 (Scar_Multiplier)**：`_get_scar_multiplier` 对情绪分做的乘法放大（`score = min(1.0, score * scar_mult)`）。
- **last_emotion_score**：持久化到 `anima_state.json` 的最近一次情绪分，供上下文注入。
- **世界观关系 (Worldview_Relationships)**：`worldview.json` 中的 `relationships` 字段，键为 `"uid -> uid"`，值为关系描述，合并写入并保留最近 30 条。
- **欲望 (Desire)**：欲望队列中的字典条目，字段含 `id` / `content` / `source` / `kind` / `intensity` / `created_at` / `target_user` / `target_umo` / `satisfied`。
- **inward / outward 欲望**：`kind` 字段。`inward` 仅注入上下文不主动外发；`outward` 可被 `_danger_stance_propagation` 触发主动发言。本特性合并产出的欲望沿用 `kind="outward"`、`source="relationship"`。
- **sylanne_state**：经 `_try_read_sylanne_state` 读取的 Sylanne 插件关系状态字符串（最长 200 字符），为空时欲望子任务不产出。
- **特性开关 (Merge_Feature_Flag)**：本特性新增的配置项 `sediment_merge_llm_calls`，用于在合并路径与旧的分离调用路径之间切换。
- **旧路径 (Legacy_Path)**：合并前的实现，即依次调用 `_evaluate_emotion`、`_danger_relationship_inference`、`_maybe_generate_desire` 三次独立内部 LLM 调用。

## Requirements

### Requirement 1: 合并为单次结构化调用

**User Story:** 作为插件运维者，我希望沉淀流程把三次内部 LLM 调用合并为一次结构化 JSON 调用，以便把内部调用的 token 成本降低约三分之二。

#### Acceptance Criteria

1. WHERE `sediment_merge_llm_calls` 配置为开启，THE Merged_Evaluator SHALL 在单次沉淀流程中仅发起一次内部 LLM 调用以产出情绪分、世界观关系与欲望三类结果。
2. WHEN Merged_Evaluator 发起内部 LLM 调用，THE Merged_Evaluator SHALL 通过 `_get_provider_id(event)` 解析模型 ID，使其在配置了 `internal_provider_id` 时优先使用该模型。
3. IF `_get_provider_id(event)` 返回空字符串，THEN THE Merged_Evaluator SHALL 返回情绪分 0.0 并跳过关系与欲望产出。
4. WHEN Merged_Evaluator 发起内部 LLM 调用，THE Merged_Evaluator SHALL 为该调用设置 15 秒超时上限。
5. IF 合并调用超过 15 秒超时上限，THEN THE Merged_Evaluator SHALL 返回情绪分 0.0 并跳过关系与欲望产出。
6. THE Merged_Evaluator SHALL 要求 LLM 返回单个 JSON 对象，包含字段 `emotion_score`（0–1 浮点数）、`relationships`（对象映射，仅在请求时）、`desire`（字符串或 null/"无"，仅在请求时）。

### Requirement 2: 按开关条件化组装提示词与输出字段

**User Story:** 作为关注成本的用户，我希望被关闭的子任务不再进入合并提示词，以便已禁用的功能不再消耗 token。

#### Acceptance Criteria

1. THE Prompt_Assembler SHALL 在合并提示词中始终包含情绪评估分段，并在请求字段中始终要求 `emotion_score`。
2. WHERE `danger_relationship_inference` 与 `worldview_enabled` 同时开启，THE Prompt_Assembler SHALL 在合并提示词中包含关系推断分段，并在请求字段中要求 `relationships`。
3. IF `danger_relationship_inference` 与 `worldview_enabled` 中任意一项关闭，THEN THE Prompt_Assembler SHALL 从合并提示词中省略关系推断分段，并从请求字段中省略 `relationships`。
4. WHERE `desire_enabled` 开启 WHEN sylanne_state 为非空字符串，THE Prompt_Assembler SHALL 在合并提示词中包含欲望生成分段，并在请求字段中要求 `desire`。
5. IF `desire_enabled` 关闭，THEN THE Prompt_Assembler SHALL 从合并提示词中省略欲望生成分段，并从请求字段中省略 `desire`。
6. IF sylanne_state 为空字符串，THEN THE Prompt_Assembler SHALL 从合并提示词中省略欲望生成分段，并从请求字段中省略 `desire`。
7. WHILE 关系推断分段与欲望生成分段均被省略，THE Merged_Evaluator SHALL 使合并调用退化为仅执行情绪评估，产出与旧路径 `_evaluate_emotion` 等价的情绪分。

### Requirement 3: 结构化响应解析与降级策略

**User Story:** 作为插件运维者，我希望在合并 JSON 输出无法解析时仍能稳妥得到情绪分，以便最关键的沉淀总闸不被一次格式错误击穿。

#### Acceptance Criteria

1. WHEN Response_Parser 收到合并调用返回文本，THE Response_Parser SHALL 先剥离 Markdown 代码围栏（前导 ```` ```json ```` 或 ```` ``` ````、结尾 ```` ``` ````）再解析 JSON。
2. WHEN JSON 解析成功，THE Response_Parser SHALL 把 `emotion_score` 钳制到 0.0–1.0 区间后作为情绪分输出。
3. IF JSON 解析失败，THEN THE Response_Parser SHALL 以最佳努力正则方式从原始文本中提取首个 0–1 之间的数字作为情绪分，并跳过本轮关系与欲望产出。
4. IF JSON 解析失败 且 正则无法提取有效情绪分，THEN THE Response_Parser SHALL 返回情绪分 0.0 并跳过本轮关系与欲望产出。
5. IF JSON 解析成功 但 缺失 `emotion_score` 字段或其值非数字，THEN THE Response_Parser SHALL 返回情绪分 0.0。
6. WHEN 解析失败触发降级，THE Merged_Evaluator SHALL NOT 回退为重新发起旧路径的三次分离调用（以保证 token 节省不被抵消）。

### Requirement 4: 情绪分下游兼容

**User Story:** 作为开发者，我希望合并后的情绪分仍按既有方式流经下游，以便阈值门控与持久化行为保持不变。

#### Acceptance Criteria

1. WHEN Merged_Evaluator 产出情绪分，THE Sediment_Process SHALL 对该分应用伤痕放大（`score = min(1.0, score * scar_mult)`），与旧路径一致。
2. WHEN 情绪分经伤痕放大后，THE Sediment_Process SHALL 将其持久化为 `last_emotion_score`。
3. IF 情绪分低于配置 `emotion_threshold`，THEN THE Sediment_Process SHALL 触发 `_stat_bump("sediment.skip_low")` 并跳过后续沉淀链。
4. WHILE 情绪分大于 0.9，THE Sediment_Process SHALL 保留既有的伤痕维度检测与 `_add_scar` 行为不变。

### Requirement 5: 世界观关系下游兼容

**User Story:** 作为开发者，我希望合并产出的关系映射仍按既有方式写入世界观，以便关系图谱数据形态与上限不变。

#### Acceptance Criteria

1. WHEN 合并响应包含非空 `relationships` 对象映射，THE Sediment_Process SHALL 在写入前对其文本应用 `_is_rejected` 过滤，命中拒答时丢弃该映射。
2. WHEN `relationships` 映射通过过滤，THE Sediment_Process SHALL 将其 `update` 合并进 `worldview.json` 的 `relationships` 字段。
3. WHILE 合并后 `relationships` 条目数超过 30，THE Sediment_Process SHALL 仅保留最近 30 条。
4. IF 合并响应的 `relationships` 字段缺失或不是对象映射，THEN THE Sediment_Process SHALL 跳过世界观关系写入且不抛出异常。

### Requirement 6: 欲望下游兼容

**User Story:** 作为开发者，我希望合并产出的欲望仍经过既有去重与字段写入逻辑，以便欲望数据形态与过滤行为不变。

#### Acceptance Criteria

1. WHEN 合并响应包含 `desire` 字符串，THE Sediment_Process SHALL 对其应用 `_is_rejected` 过滤，命中拒答时丢弃该欲望。
2. IF `desire` 值为 null、空字符串、"无" 或长度不大于 2 个字符，THEN THE Sediment_Process SHALL 不创建欲望条目。
3. WHEN `desire` 通过拒答与长度过滤，THE Sediment_Process SHALL 调用 `_is_desire_already_expressed(desire, response_text, event)`，并在判定为已表达时跳过写入。
4. WHEN `desire` 通过全部过滤被写入，THE Sediment_Process SHALL 写入字段为 `id`、`content`、`source="relationship"`、`kind="outward"`、`intensity=0.7`、`created_at`、`target_user`、`target_umo`、`satisfied=False` 的欲望字典。
5. WHILE 欲望队列长度已达配置 `desire_max_queue`，THE Sediment_Process SHALL 不再写入新欲望。

### Requirement 7: 统计可观测性

**User Story:** 作为关注成本的用户，我希望合并调用的统计语义清晰，以便仪表盘的 token 画面既不重复计数也不丢失既有观测项。

#### Acceptance Criteria

1. WHEN Merged_Evaluator 实际完成一次合并内部 LLM 调用，THE Stats_Recorder SHALL 触发一次 `_stat_bump("llm.sediment_merged")`。
2. WHILE 走合并路径，THE Stats_Recorder SHALL NOT 触发 `_stat_bump("llm.emotion")` 或 `_stat_bump("llm.relation")`，以避免与合并计数重复累计同一次物理调用。
3. WHEN 合并响应使一条欲望被成功写入，THE Stats_Recorder SHALL 触发一次 `_stat_bump("desire.created.outward")`，与旧路径一致。
4. WHERE `sediment_merge_llm_calls` 关闭（走旧路径），THE Stats_Recorder SHALL 保留 `llm.emotion`、`llm.relation`、`desire.created.outward` 的既有埋点不变。
5. IF 配置 `dashboard_enabled` 为关闭，THEN THE Stats_Recorder SHALL 跳过所有埋点累加，与既有 `_stat_bump` 行为一致。

### Requirement 8: 特性开关与新旧路径切换

**User Story:** 作为插件运维者，我希望通过一个配置开关在合并路径与旧路径之间切换，以便降低上线风险并借助 v0.9.1 仪表盘做 A/B token 对比。

#### Acceptance Criteria

1. THE Anima SHALL 提供布尔配置项 `sediment_merge_llm_calls`，默认值为 `false`（默认走旧的分离调用路径以降低上线风险）。
2. WHERE `sediment_merge_llm_calls` 开启，THE Sediment_Process SHALL 使用 Merged_Evaluator 的单次合并调用路径。
3. WHERE `sediment_merge_llm_calls` 关闭，THE Sediment_Process SHALL 使用旧路径，依次调用 `_evaluate_emotion`、`_danger_relationship_inference`、`_maybe_generate_desire`。
4. WHEN 在两条路径之间切换配置，THE Sediment_Process SHALL 对相同输入产出形态一致的下游副作用（情绪分持久化、世界观关系写入、欲望写入），差异仅限于内部 LLM 调用次数与对应统计计数项。

### Requirement 9: 回归安全

**User Story:** 作为维护者，我希望这次触及核心沉淀链的改动有明确回归保护，以便确认既有行为不被破坏。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（沉淀改动前的全部 190 个测试），THE Anima SHALL 使其全部通过。
2. THE Anima SHALL 为合并路径新增测试，覆盖各开关组合（情绪-only、情绪+关系、情绪+欲望、情绪+关系+欲望）下提示词分段与请求字段的条件化组装。
3. THE Anima SHALL 为 Response_Parser 新增测试，覆盖 JSON 解析成功、JSON 解析失败后正则提取、解析失败且无法提取的三种降级路径。
4. THE Anima SHALL 新增测试，验证合并产出的情绪分、关系映射、欲望分别正确流入其下游消费者（伤痕放大与阈值门控、世界观关系写入与 30 条上限、欲望去重与字典写入）。
5. WHERE `sediment_merge_llm_calls` 关闭，THE Anima SHALL 通过测试验证旧路径的三次分离调用与既有埋点行为保持不变。
