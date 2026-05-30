# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.4）修复个人能力系统（Personal Capability System）的"开环增殖"缺陷。

生产实测（仪表盘真实数据）：**105 个能力 / 平均置信度 93.2% / 总使用 0 次 / 总修正 0 次**。这四个数字共同暴露了一条**从未闭合的"自我修正闭环"**：

- 能力合成时直接采用 LLM **自报的** `confidence`（自封高分，普遍 0.9+）。
- 健康修剪（`_maintain_capabilities_health`）的所有淘汰/降权规则都以"低置信度"为前提，而自封高分让这些规则**永不触发** → 修剪形同虚设 → 能力只增不减。
- 使用计数（`usage_count`）只在模型主动调用 `use_my_personal_capability` 且传对精确名字时才 +1；晦涩的能力名让这条路径几乎不触发 → 永远 0 次 → 置信度永远得不到真实校正。
- 创建期去重（`_find_similar_capability`，语义槽位）与维护期去重（`name.lower()[:12]` 前缀）**两套不一致逻辑**，且创建期去重为单一"戉系/Ego系"家族过拟合，对自由发挥的中文长名基本不命中。

本特性按三层修复：

- **P0（解死锁）**：置信度脱钩 LLM 自评，从未验证基线起步；修剪规则改为对"未使用"敏感而非只对"低置信"敏感。
- **P1（防再增殖）**：能力总数硬上限 + 超限按真实价值分淘汰；维护期复用创建期去重并将去重逻辑泛化。
- **P2（让闭环可闭合）**：新增体检命令暴露可疑能力；存量数据一次性迁移；降低使用门槛。

## Glossary

- **个人能力系统 (Capability_System)**：角色通过自主研究/经历创造的"个人方法论"集合，持久化于 `personal_capabilities.json`，受 `capability_system_enabled` 控制。
- **能力 (Capability)**：一条能力字典，字段含 `id` / `name` / `description` / `how_to_use` / `confidence` / `usage_count` / `corrections` / `created_at` / `last_updated` / `category` / `source_research` 等。
- **置信度 (Confidence)**：0–1 浮点，本应反映"这个能力用着好不好用"。当前缺陷是直接取 LLM 自报值。
- **未验证基线 (Unverified_Baseline)**：新建能力的统一初始置信度，表示"尚未经真实使用验证"。本特性引入。
- **合成路径 (Synthesis_Path)**：`danger.py` 中两处把研究成果转成能力的代码（`_initiate_self_directed_research` 内部研究合成、`_danger_autonomous_web` 联网研究合成），均调用 `_create_or_update_capability`。
- **健康维护 (Health_Maintenance)**：`_maintain_capabilities_health`，每 15 次沉淀触发一次，负责淘汰/降权/合并能力。
- **使用反馈闭环 (Feedback_Loop)**：`_apply_capability_feedback`，能力被真实使用后调整 `usage_count` 与 `confidence`，失败时追加 `correction`。
- **创建期去重 (Creation_Dedup)**：`_find_similar_capability`（委托 `capability_dedup.find_similar_capability`），新建能力时找语义近似项合并。
- **维护期去重 (Maintenance_Dedup)**：`_maintain_capabilities_health` 内的相似合并逻辑（当前用 `name[:12]` 前缀）。
- **价值分 (Value_Score)**：综合 `usage_count`、`corrections`、新近度计算的能力排序分，**不含自封 confidence**，用于超限淘汰。
- **体检 (Audit)**：扫描能力库找出可疑条目（0 使用 + 高置信、过期未用等）的只读诊断。

## Requirements

### Requirement 1: 置信度脱钩 LLM 自评（P0）

**User Story:** 作为插件运维者，我希望新建能力的置信度不再由 LLM 自报决定，以便置信度真实反映使用效果而非自我吹嘘。

#### Acceptance Criteria

1. THE Capability_System SHALL 提供配置项 `capability_initial_confidence`（float，默认 `0.3`）作为未验证基线。
2. WHEN 合成路径创建一条**新**能力，THE Capability_System SHALL 忽略 LLM 自报的 `confidence`，统一使用 `capability_initial_confidence` 作为初始置信度。
3. WHEN `_create_or_update_capability` 创建新能力且 payload 未显式给出受信来源的 confidence，THE Capability_System SHALL 将其 `confidence` 设为 `capability_initial_confidence`。
4. THE Capability_System SHALL 仅允许 `_apply_capability_feedback`（真实使用反馈）提升能力置信度。
5. WHILE 一条能力从未被使用（`usage_count == 0`），THE Capability_System SHALL NOT 使其 `confidence` 超过 `capability_initial_confidence`。

### Requirement 2: 修剪对"未使用"敏感（P0）

**User Story:** 作为插件运维者，我希望长期没被用过的能力会自然老化退场，以便能力库不再因自封高分而只增不减。

#### Acceptance Criteria

1. WHERE 一条能力 `usage_count == 0` 且距 `last_updated` 超过 `capability_unused_decay_days`（int，默认 `14`）天，THE Health_Maintenance SHALL 对其置信度降权（乘以 `0.9`，下限 `0.05`），不受其当前置信度高低影响。
2. WHERE 一条能力 `usage_count == 0` 且距 `last_updated` 超过 `capability_unused_drop_days`（int，默认 `30`）天，THE Health_Maintenance SHALL 淘汰该能力，不受其当前置信度高低影响。
3. THE Health_Maintenance SHALL 保留既有的"极低置信 + 极少使用 + 陈旧"淘汰规则作为补充。
4. WHEN Health_Maintenance 执行任何淘汰/降权/合并，THE Capability_System SHALL 持久化结果并记录到演化日志。

### Requirement 3: 能力总数硬上限与价值淘汰（P1）

**User Story:** 作为插件运维者，我希望能力库有一个明确的总数上限，以便防止增殖失控的最坏情况。

#### Acceptance Criteria

1. THE Capability_System SHALL 提供配置项 `capability_max_total`（int，默认 `40`）。
2. WHILE Health_Maintenance 完成常规淘汰/合并后能力数仍超过 `capability_max_total`，THE Health_Maintenance SHALL 按价值分升序淘汰最差者，直至数量不超过上限。
3. THE Value_Score SHALL 由 `usage_count`、`corrections` 数量、新近度（距 `last_updated` 天数）综合计算，且 SHALL NOT 包含能力自报的 `confidence`。
4. WHEN 因超限淘汰能力，THE Capability_System SHALL 将淘汰数量记入演化日志。

### Requirement 4: 去重逻辑统一与泛化（P1）

**User Story:** 作为开发者，我希望创建期与维护期用同一套去重逻辑，且对任意主题的能力都有效，以便同概念能力能被可靠合并而不只针对单一家族。

#### Acceptance Criteria

1. THE Maintenance_Dedup SHALL 复用 Creation_Dedup（`_find_similar_capability`），不再使用 `name[:12]` 前缀匹配。
2. THE Creation_Dedup SHALL 在语义槽位匹配之外，增加基于名称与描述的通用文本相似度判定（覆盖无核心槽位的中文长名能力）。
3. WHEN 两条能力的通用文本相似度不低于 `capability_dedup_text_threshold`（float，默认 `0.6`），THE Creation_Dedup SHALL 判定为近似并合并。
4. WHILE 泛化去重生效，THE Creation_Dedup SHALL 保持既有 `test_capability_dedup.py` 中"不相关能力不误合并"的全部断言通过（不得提高误合并率）。
5. WHEN 合并两条能力，THE Capability_System SHALL 累计 `usage_count` 并合并 `corrections` 历史。

### Requirement 5: 能力体检命令（P2）

**User Story:** 作为插件管理员，我希望有一个命令快速看出能力库的健康状况，以便判断是否需要清理。

#### Acceptance Criteria

1. THE Capability_System SHALL 提供管理命令 `/anima_capabilities_audit`。
2. WHEN 管理员执行 `/anima_capabilities_audit`，THE Capability_System SHALL 返回：能力总数、平均置信度、总使用次数、总修正次数、0 使用能力数量、疑似自封高分（`usage_count == 0` 且 `confidence > capability_initial_confidence`）数量及样本。
3. THE Audit SHALL 为只读，不修改任何能力数据，不调用 LLM。
4. WHEN 能力库为空，THE Audit SHALL 返回明确的空状态提示。

### Requirement 6: 存量数据迁移（P2）

**User Story:** 作为插件运维者，我希望升级后历史的自封高分能力被一次性归正，以便修复立即对现有 105 个能力生效。

#### Acceptance Criteria

1. WHEN 插件升级后首次加载能力库 且 检测到尚未迁移标记，THE Capability_System SHALL 对所有 `usage_count == 0` 的能力将其 `confidence` 重置为不超过 `capability_initial_confidence`。
2. WHEN 完成存量迁移，THE Capability_System SHALL 写入迁移标记（如能力库的 `migrated_v094` 字段），避免重复迁移。
3. THE 存量迁移 SHALL NOT 删除任何能力（仅调整置信度），后续淘汰交由 Health_Maintenance 按未使用规则处理。
4. WHERE 一条能力 `usage_count > 0`，THE 存量迁移 SHALL 保留其现有置信度不变（真实用过的不归正）。

### Requirement 7: 降低使用门槛（P2）

**User Story:** 作为使用者，我希望角色能更容易地真正用上自己的能力，以便使用反馈闭环有机会闭合。

#### Acceptance Criteria

1. THE Capability_System SHALL 在注入上下文时按价值分（而非自封 confidence）排序展示能力，优先呈现真实用过的能力。
2. WHEN `use_my_personal_capability` 收到的 `capability_name` 与库中某能力名不精确相等但高度相似（不区分大小写的子串或文本相似度达阈值），THE Capability_System SHALL 解析到该能力而非报"找不到"。
3. THE Capability_System SHALL 在能力注入上下文文本中包含一条引导，鼓励模型按场景主动调用已有能力。

### Requirement 8: 回归安全

**User Story:** 作为维护者，我希望这次改动有明确回归保护，以便确认既有行为不被破坏。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 220 个测试），THE Capability_System SHALL 使其全部通过。
2. THE Capability_System SHALL 新增测试覆盖：置信度脱钩自评、未使用降权/淘汰、硬上限价值淘汰、维护期与创建期去重一致、存量迁移、体检命令输出、模糊名解析。
3. WHERE `capability_system_enabled` 关闭，THE Capability_System SHALL 维持既有"不创建/不注入/不注册"的行为不变。
