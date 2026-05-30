# Requirements Document

## Introduction

本特性（Anima 插件 **v0.9.10**）解决个人能力系统（Personal Capability System）的**核心使用闭环未闭合**问题：能力被大量创造但**几乎从不被真实调用**。

生产实测：**105 个能力 / 总使用 0 次**。v0.9.4（`capability-system-closed-loop`）已经修掉了"自封高分导致只增不减"——置信度脱钩自评、未使用降权/淘汰、价值分排序、模糊名解析、存量迁移——但**没有**解决"能力极少被调用"这一根因。

### 已确认的三条根因（代码级）

1. **置信度死锁（可发现性）**：新能力从基线置信度起步（`capability_initial_confidence`，默认 `0.3`），**只有真实使用**经 `_apply_capability_feedback` 才能提升置信度；但要成为可被发现的"独立命名 LLM 工具"，当前要求 `confidence >= 0.65`（`_create_or_update_capability` 内）。于是：没用过 → 分低 → 不被提升为命名工具 → 不被发现 → 不被用过。**死循环**。
2. **纯靠模型自觉（意愿）**：能力以叙事方式注入系统提示（`_get_personal_capabilities_injection`，`main.py:603`），并仅通过一个通用工具 `use_my_personal_capability` 暴露。模型必须自己注意到、决定调用、并传入一个可解析的 `capability_name`。实践中模型往往直接作答，`usage_count`（置信度唯一能增长之处）几乎从不 +1。
3. **能力描述含糊（质量）**：合成出的能力描述模糊，且没有显式的"何时使用"触发字段（`when_to_use`），模型与任何匹配器都无法判断某能力何时适用。

### 强化方案（三层 + 一条度量闭环）

- **Layer 1 — 打破死锁（可发现性）**：放弃用 `confidence >= 0.65` 作为注册命名工具的门槛，改用**晋升模型**——按 `_capability_value_score` 取 Top-K 注册为命名独立 LLM 工具（"能力工具带"），在 `initialize()` 与每次健康维护后刷新。新能力（哪怕 `0.3` 置信度）获得一个有限"试用名额"，从而能被看见、被调用，赚到唯一能提升置信度的真实使用。受小 K（默认 3）、既有每日注册配额、能力总数上限约束。新配置 `capability_promote_enabled` **默认 FALSE**（token 成本，遵循"高 token 特性默认关"约定），但文档强烈推荐开启；关闭时行为与今天完全一致（无回归）。
- **Layer 2 — 相关性触发的定向提示（意愿）**：在 `on_llm_request` 注入能力的同一处，用 `anima/similarity.py` 现有**免费**相似度函数（`text_token_set` / `jaccard_similarity`）计算当前用户消息与每个能力 `description` / `when_to_use` 的词法相关性（embedding 经 `_embed_one` 为可选升级路径，失败降级为 Jaccard）。当最高相关性 ≥ 阈值时，在能力列表旁注入一句定向提示。纯词法匹配同步、零额外 LLM 调用、近乎免费，仅在命中时注入（不命中零 token）。**默认 ON**（因为免费），阈值与后端可配。
- **Layer 3 — 合成质量：要求 when_to_use（质量）**：合成路径（`danger.py` 两处 → `_create_or_update_capability`）要求每个能力携带一个具体的 `when_to_use` 触发描述。Layer 2 的匹配消费此字段。向后兼容：没有 `when_to_use` 的存量能力回退到 `description` 匹配。**默认 ON**（无 token 成本，仅在合成提示里多要一个字段）。
- **度量闭环（关键）**：新增 `_stat_bump` 埋点，让 `/anima_capabilities_audit` 与仪表盘能看出强化是否生效：`capability.call.attempt` / `capability.call.resolved` / `capability.call.unresolved` / `capability.match.hint_injected` / `capability.promoted`。一周后对比 `total_usage` 是否上升、hint→call 的转化率。

### 已锁定的决策（用户确认）

- `capability_promote_enabled` 默认 **OFF**，文档推荐 ON。
- Top-K 默认 **3**。
- Layer 2 默认 **词法匹配**，embedding 为可选。

## Glossary

- **个人能力系统 (Capability_System)**：角色通过自主研究/经历创造的"个人方法论"集合，持久化于 `personal_capabilities.json`，受 `capability_system_enabled` 控制。
- **能力 (Capability)**：一条能力字典，字段含 `id` / `name` / `description` / `how_to_use` / `confidence` / `usage_count` / `corrections` / `created_at` / `last_updated` / `category` / `register_as_independent_tool` 等；本特性新增可选 `when_to_use` 字段。
- **价值分 (Value_Score)**：`_capability_value_score`，由 `usage_count`、`corrections` 数量、新近度综合计算的能力排序分，**不含自封 `confidence`**。
- **晋升 (Promotion)**：本特性引入。按价值分取 Top-K 能力注册为命名独立 LLM 工具的过程，替代旧的"`confidence >= 0.65` 才注册"门槛。
- **能力工具带 (Capability_Tool_Belt)**：被晋升、当前注册为独立命名 LLM 工具的能力集合。
- **试用名额 (Trial_Slot)**：Layer 1 在 Top-K 名额中为"从未被晋升过的新能力"保留的至少一个名额，确保新能力能被看见与调用，从而获得真实使用。
- **独立命名工具 (Named_Tool)**：经 `_dynamically_register_capability_as_tool` 注册到 `context` 的、以能力命名的 `FunctionTool`，模型可直接发现并调用（区别于通用的 `use_my_personal_capability`）。
- **每日注册配额 (Daily_Register_Quota)**：`dynamic_tool_daily_quota`（默认 3），既有的每日动态工具注册上限。
- **能力总数上限 (Max_Total)**：`capability_max_total`（默认 40），既有的能力总数硬上限。
- **能力注入 (Capability_Injection)**：`_get_personal_capabilities_injection`，把能力以第一人称叙事注入系统提示的文本（注入点在 `main.py:603` 的 `on_llm_request`）。
- **定向提示 (Relevance_Hint)**：Layer 2 在能力注入文本旁追加的一句短提示，指向与当前用户消息最相关的能力。
- **词法相关性 (Lexical_Relevance)**：`anima/similarity.py` 的 `text_token_set` + `jaccard_similarity`（便捷封装 `text_jaccard`）计算的、用户消息与能力文本之间的相似度，纯本地、零 LLM。
- **匹配文本 (Match_Text)**：参与 Layer 2 相关性计算的能力文本：优先 `when_to_use`，缺失或为空则回退 `description`。
- **合成路径 (Synthesis_Path)**：`danger.py` 中两处把研究成果转成能力的代码（`_initiate_self_directed_research`、`_danger_autonomous_web`），均调用 `_create_or_update_capability`。
- **派发器 (Dispatcher)**：通用工具 `use_my_personal_capability`，接受 `capability_name` + `query_or_args`，经 `_resolve_capability` 解析后执行能力。
- **健康维护 (Health_Maintenance)**：`_maintain_capabilities_health`，负责淘汰/降权/合并能力；本特性在其后刷新能力工具带。
- **度量埋点 (Metrics_Loop)**：`_stat_bump`（`anima/mixins/stats.py`，受 `dashboard_enabled` 控制，自身零 token、绝不抛异常），本特性新增 5 个计数 key。

## Requirements

### Requirement 1: 晋升模型——打破置信度死锁（Layer 1 / P0）

**User Story:** 作为插件运维者，我希望高价值能力即使置信度不足 0.65 也能被注册为命名独立工具，以便新能力能被模型发现和调用，从而赚到唯一能提升置信度的真实使用。

#### Acceptance Criteria

1. THE Capability_System SHALL 提供配置项 `capability_promote_enabled`（bool，默认 `false`）。
2. THE Capability_System SHALL 提供配置项 `capability_promote_top_k`（int，默认 `3`）。
3. WHERE `capability_promote_enabled` 为 `true`，THE Capability_System SHALL 在 `initialize()` 与每次 Health_Maintenance 完成后，按 Value_Score 降序选出至多 `capability_promote_top_k` 个能力注册为 Named_Tool。
4. WHEN 选择晋升能力，THE Capability_System SHALL 仅依据 Value_Score 排序，SHALL NOT 要求能力 `confidence >= 0.65`。
5. WHERE `capability_promote_enabled` 为 `true` 且存在至少一个 `usage_count == 0` 且从未被晋升过的能力，THE Capability_System SHALL 在 `capability_promote_top_k` 个名额中为该类新能力保留至少一个 Trial_Slot。
6. WHEN 执行晋升注册，THE Capability_System SHALL 遵守既有 Daily_Register_Quota（`dynamic_tool_daily_quota`），使本次新注册的 Named_Tool 数不超过当日剩余配额。
7. THE Capability_Tool_Belt 的大小 SHALL NOT 超过 `capability_promote_top_k`。
8. WHEN 一个能力被成功晋升为 Named_Tool，THE Metrics_Loop SHALL 对 `capability.promoted` 累加。

### Requirement 2: 晋升的回归安全与成本边界（Layer 1 / P0）

**User Story:** 作为插件运维者，我希望晋升默认关闭且开销可控，以便在不增加 token 成本的前提下零回归升级。

#### Acceptance Criteria

1. WHERE `capability_promote_enabled` 为 `false`，THE Capability_System SHALL 维持 v0.9.4 既有注册行为不变（仅 `confidence >= 0.65` 且带 `register_as_independent_tool` 标记的能力按既有逻辑注册），且 SHALL NOT 因晋升而额外注册任何 Named_Tool。
2. WHERE `capability_system_enabled` 为 `false`，THE Capability_System SHALL NOT 执行任何晋升、注册或刷新动作。
3. WHEN 晋升刷新能力工具带，THE Capability_System SHALL 跳过已注册的同名工具，不重复注册。
4. IF 晋升注册过程中抛出异常，THEN THE Capability_System SHALL 捕获该异常并继续主流程，不影响对话或健康维护。
5. THE `capability_promote_enabled` 配置项 SHALL 在 `_conf_schema.json` 标注为高 token 提示，且文档 SHALL 推荐开启。

### Requirement 3: 相关性触发的定向提示（Layer 2 / P1）

**User Story:** 作为使用者，我希望当我的消息明显匹配某个能力时，系统主动提示模型优先调用该能力，以便被动的叙事注入变成场景命中时的明确推动。

#### Acceptance Criteria

1. THE Capability_System SHALL 提供配置项 `capability_match_hint_enabled`（bool，默认 `true`）。
2. THE Capability_System SHALL 提供配置项 `capability_match_hint_threshold`（float，默认 `0.2`）作为注入定向提示的最低相关性阈值。
3. THE Capability_System SHALL 提供配置项 `capability_match_hint_backend`（string，默认 `"lexical"`，可选 `"embedding"`）。
4. WHERE `capability_match_hint_enabled` 为 `true`，WHEN 处理 `on_llm_request` 且存在能力，THE Capability_System SHALL 用 Lexical_Relevance 计算当前用户消息与每个能力 Match_Text 的相关性。
5. IF 最高相关性 `>= capability_match_hint_threshold`，THEN THE Capability_System SHALL 在能力注入文本旁注入一条 Relevance_Hint，指向相关性最高的那一个能力。
6. WHILE 所有能力的相关性都低于 `capability_match_hint_threshold`，THE Capability_System SHALL NOT 注入任何 Relevance_Hint（不命中零 token）。
7. WHERE `capability_match_hint_backend` 为 `"embedding"` 且 embedding 不可用或计算失败，THE Capability_System SHALL 降级为 Lexical_Relevance（Jaccard），不抛异常。
8. WHEN 注入一条 Relevance_Hint，THE Metrics_Loop SHALL 对 `capability.match.hint_injected` 累加。
9. WHERE `capability_match_hint_enabled` 为 `false`，THE Capability_System SHALL 维持既有能力注入文本不变，不做相关性计算、不注入提示。

### Requirement 4: 合成时要求 when_to_use 触发描述（Layer 3 / P2）

**User Story:** 作为插件运维者，我希望新合成的能力带有具体的"何时使用"描述，以便相关性匹配与定向提示有可靠依据。

#### Acceptance Criteria

1. WHEN Synthesis_Path 请求 LLM 合成能力，THE Capability_System SHALL 在合成提示中要求输出 `when_to_use` 字段（描述该能力适用的具体场景）。
2. WHEN Synthesis_Path 创建能力且 LLM 返回了 `when_to_use`，THE Capability_System SHALL 将 `when_to_use` 持久化到能力字典。
3. WHERE 一个能力缺失 `when_to_use` 或其值为空，THE Capability_System SHALL 在 Layer 2 相关性计算时回退使用 `description` 作为 Match_Text。
4. THE Capability_System SHALL 保证缺失 `when_to_use` 的存量能力继续正常工作（创建、注入、匹配、调用均不报错）。

### Requirement 5: 调用度量埋点（Metrics / P1）

**User Story:** 作为插件运维者，我希望能量化看到能力被调用的尝试、成功解析与失败解析，以便判断三层强化是否真的提升了使用率。

#### Acceptance Criteria

1. WHEN Dispatcher（`use_my_personal_capability`）或任意 Named_Tool 被调用，THE Metrics_Loop SHALL 对 `capability.call.attempt` 累加。
2. WHEN 一次调用经 `_resolve_capability` 成功解析到某能力，THE Metrics_Loop SHALL 对 `capability.call.resolved` 累加。
3. IF 一次调用的 `capability_name` 无法解析到任何能力，THEN THE Metrics_Loop SHALL 对 `capability.call.unresolved` 累加。
4. THE Capability_System SHALL 使每一次 `capability.call.attempt` 恰好对应一次 `capability.call.resolved` 或一次 `capability.call.unresolved`（互斥且穷尽，二者之和等于尝试数）。
5. WHERE `dashboard_enabled` 为 `false`，THE Metrics_Loop SHALL 跳过累加（沿用既有 `_stat_bump` 行为），且埋点 SHALL NOT 抛出影响主流程的异常。

### Requirement 6: 向后兼容与零数据丢失

**User Story:** 作为插件运维者，我希望升级到 v0.9.10 不破坏现有数据与行为，以便安全升级。

#### Acceptance Criteria

1. THE Capability_System SHALL 保持现有 `personal_capabilities.json` 可继续读写，缺失 `when_to_use` 字段的能力照常工作。
2. THE 本特性 SHALL NOT 删除或改写任何现有能力字段的语义（仅新增可选 `when_to_use` 字段与晋升/提示/埋点行为）。
3. WHERE 三个新特性开关（`capability_promote_enabled=false`、`capability_match_hint_enabled` 视配置、Layer 3 仅多一个被请求字段）按默认值组合，THE Capability_System SHALL 仅在 Layer 2 命中时新增提示文本，其余行为与 v0.9.4 完全一致。
4. THE 新配置项默认值 SHALL 遵循项目约定：高 token 特性（晋升）默认 `false`，免费特性（提示、`when_to_use`）默认 `true`。

### Requirement 7: 回归安全与测试

**User Story:** 作为维护者，我希望本次改动有明确回归保护与属性测试覆盖，以便确认既有行为不被破坏且新逻辑正确。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 310 个测试），THE Capability_System SHALL 使其全部通过。
2. THE 本特性 SHALL 新增 Hypothesis 属性测试，每条测试单一属性、迭代次数 `>= 100`，并以注释 `# Feature: capability-loop-strengthening, Property N: ...` 标注。
3. THE 新增测试 SHALL 覆盖：晋升 Top-K 选择与不依赖 confidence、晋升默认关无回归、Trial_Slot、Layer 2 命中即注入/不命中不注入、embedding 降级、Layer 3 回退 description、调用埋点的互斥穷尽性。
4. THE 新增测试 SHALL 沿用 `tests/` 既有 `types.ModuleType` 桩 + 最小宿主类约定，不依赖真实 `astrbot.*` 运行时。
5. WHERE 某验收标准属于"行为不随输入变化"或"测试外部服务/框架接线"，THE 测试策略 SHALL 使用 1–3 个代表性示例的集成/单元测试，而非属性测试（避免对纯接线做 100 次迭代）。

## Correctness Properties

> 以下属性面向属性测试（Hypothesis，≥100 迭代，每属性单测试）。括注的 Validates 指向上文验收标准。

### Property 1: 晋升 Top-K 选择正确性
*对任意*能力集合与 `K = capability_promote_top_k`，在 `capability_promote_enabled=true` 下计算的晋升集合大小 `<= K`，且晋升集合中任一能力的 Value_Score 不低于未晋升能力中的最大 Value_Score（即严格按价值分取 Top-K）。
**Validates: Requirements 1.3, 1.7**

### Property 2: 晋升不依赖自封置信度（解死锁）
*对任意*能力集合，若某能力 `confidence < 0.65`（含新建 `0.3` 基线）但其 Value_Score 排在 Top-K 内，则它被纳入晋升集合；反之，仅靠高 `confidence` 而 Value_Score 不在 Top-K 的能力不会被晋升。两条能力若 `usage_count`/`corrections`/`last_updated` 相同而 `confidence` 不同，其晋升资格相同。
**Validates: Requirements 1.4, 2.1**

### Property 3: Trial_Slot 保证新能力可见
*对任意*同时包含"高价值老能力"与"至少一个 `usage_count==0` 且从未晋升的新能力"的集合，在 `capability_promote_enabled=true` 下，晋升集合中至少包含一个该类新能力（占用 Trial_Slot）。
**Validates: Requirements 1.5**

### Property 4: 晋升默认关无回归
*对任意*能力集合，当 `capability_promote_enabled=false` 时，因晋升而新注册的 Named_Tool 数为 `0`（注册行为退化为 v0.9.4 既有逻辑）。
**Validates: Requirements 2.1, 6.3**

### Property 5: 晋升受配额上界约束
*对任意*能力集合与当日已用配额，本次晋升新注册的 Named_Tool 数 `<= min(K, 当日剩余 dynamic_tool_daily_quota)`，且能力工具带大小 `<= K`。
**Validates: Requirements 1.6, 1.7**

### Property 6: Layer 2 命中即注入、不命中不注入
*对任意*用户消息与能力集合，在 `capability_match_hint_enabled=true` 下：当且仅当最高 Lexical_Relevance `>= capability_match_hint_threshold` 时注入恰好一条 Relevance_Hint，且该提示指向相关性最高的能力；当所有相关性低于阈值时，注入文本等于无提示的基础注入文本（零额外 token）。
**Validates: Requirements 3.5, 3.6**

### Property 7: Layer 2 后端降级不抛异常
*对任意*输入，当 `capability_match_hint_backend="embedding"` 且 embedding 不可用/失败时，相关性计算降级为 Jaccard 并返回有限非负值，绝不抛出异常。
**Validates: Requirements 3.7**

### Property 8: Layer 3 Match_Text 回退
*对任意*能力，参与 Layer 2 计算的 Match_Text 等于：当 `when_to_use` 存在且非空时取 `when_to_use`，否则取 `description`；缺失 `when_to_use` 的能力相关性计算返回有限非负值且不报错。
**Validates: Requirements 4.3, 4.4**

### Property 9: 调用埋点互斥穷尽
*对任意*一串能力调用序列，`capability.call.attempt` 的累加值等于 `capability.call.resolved` 与 `capability.call.unresolved` 累加值之和（每次尝试被恰好分类一次）。
**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
