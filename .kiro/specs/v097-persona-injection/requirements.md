# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.7）补齐当前最弱的维度——**角色人设传入**（审计评分 4/10）。

现状问题：

- Anima 唯一的"人设入口"是 `persona_core.yaml`，且它通过 `req.extra_user_content_parts` 注入到**用户消息**里，而非 system prompt。对 system/user 角色敏感的模型，人设权重被削弱。
- 没有"在 WebUI 配置里直接写角色人设 prompt"的入口；要改人设得手动编辑 YAML 文件。
- `persona_core.yaml` 会被 `danger_core_mutation` 自动改写，用户写死的人设可能被角色自我演化覆盖，无法锁定。
- 三层人设（AstrBot 框架 system prompt / `persona_core.yaml` / `seed_persona`）关系不清，用户不知道该在哪写什么。

本特性提供：一个 WebUI 可编辑的 `persona_prompt` 配置项，**注入到 system prompt**；一个"锁定人设"开关，开启后 `danger_core_mutation` 不能改写核心人设；并在文档里厘清三层人设关系。

## Glossary

- **人设 prompt (Persona_Prompt)**：本特性新增的配置项 `persona_prompt`，用户直接填写的角色人设文本，注入到 system prompt。
- **system prompt 注入 (System_Prompt_Injection)**：通过修改 `req.system_prompt`（`ProviderRequest.system_prompt: str`）把人设放到系统角色，而非用户消息。
- **核心人设文件 (Persona_Core)**：`persona_core.yaml`，Anima 的行为边界与自我认知规则，可被 `danger_core_mutation` 改写。
- **人设锁定 (Persona_Lock)**：本特性新增开关 `persona_lock`，开启后 `danger_core_mutation` 不写盘、不改写 Persona_Core。
- **核心突变 (Core_Mutation)**：`_danger_core_mutation`，每 100 次沉淀改写 `persona_core.yaml`。
- **种子人设 (Seed_Persona)**：配置项 `seed_persona`，仅在 `self_notes.md` 为空时作为初始自我认知种子写入一次。
- **自我觉知注入块 (Self_Awareness_Block)**：当前 `<anima_self_awareness>` 包裹的、注入到用户消息的所有 Anima 状态（self_notes/欲望/世界观等）。

## Requirements

### Requirement 1: 人设 prompt 配置项并注入 system prompt

**User Story:** 作为使用者，我希望在 WebUI 配置里直接写角色人设并让它进入 system prompt，以便人设以最高权重稳定生效。

#### Acceptance Criteria

1. THE Anima SHALL 提供文本配置项 `persona_prompt`（text，默认空）。
2. WHERE `persona_prompt` 为非空字符串，THE Anima SHALL 在 `on_llm_request` 中把其内容注入到 `req.system_prompt`。
3. WHEN 注入人设到 system prompt，THE Anima SHALL 将 `persona_prompt` 置于既有 `req.system_prompt` 内容之前（人设优先），并以换行分隔保留原有 system prompt。
4. WHERE `persona_prompt` 为空，THE Anima SHALL 不修改 `req.system_prompt`（保持框架原值）。
5. THE Persona_Prompt 注入 SHALL 独立于 Self_Awareness_Block（用户消息块）；两者可同时存在且互不覆盖。

### Requirement 2: 人设锁定开关

**User Story:** 作为使用者，我希望锁定我写死的人设，以便角色的自我演化（核心突变）不会偷偷改掉它。

#### Acceptance Criteria

1. THE Anima SHALL 提供布尔配置项 `persona_lock`（默认 `false`）。
2. WHERE `persona_lock` 为 `true`，THE Core_Mutation SHALL 不写入 `persona_core.yaml`、不记录突变历史、提前返回，并记录一次说明日志。
3. WHERE `persona_lock` 为 `true`，THE Anima SHALL NOT 阻止其它非写盘的演化机制（情绪/欲望/世界观仍正常）。
4. WHERE `persona_lock` 为 `false`，THE Core_Mutation SHALL 维持既有行为（含 v0.9.5 的 YAML 校验）。

### Requirement 3: 三层人设关系厘清（文档）

**User Story:** 作为使用者，我希望清楚三层人设各写什么，以便正确配置不混淆。

#### Acceptance Criteria

1. THE Anima SHALL 在 README 中以表格说明三层人设的分工：AstrBot 框架 system prompt（基础人设/说话风格）、`persona_prompt`（Anima 注入 system 的人设）、`persona_core.yaml`（行为边界与自我认知规则）、`seed_persona`（一次性初始自我种子）。
2. THE 文档 SHALL 说明注入位置差异：`persona_prompt` → system prompt；`persona_core.yaml` 与其它状态 → 用户消息块。
3. THE 文档 SHALL 说明 `persona_lock` 与 `danger_core_mutation` 的关系。

### Requirement 4: 配置项 token 标注

**User Story:** 作为关注成本的用户，我希望新配置项标注 token 影响。

#### Acceptance Criteria

1. THE `persona_prompt` 配置 hint SHALL 标注：增加每轮 system prompt 的输入 token（🟡），内容越长越费。
2. THE `persona_lock` 配置 hint SHALL 标注：⚪ Token 无（仅开关行为）。

### Requirement 5: 回归安全

**User Story:** 作为维护者，我希望本次改动有明确回归保护。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 273 个测试），THE Anima SHALL 使其全部通过。
2. THE Anima SHALL 新增测试覆盖：persona_prompt 注入 system prompt（非空/空）、persona_lock 阻止核心突变写盘、persona_lock=false 时不阻止。
3. WHERE `persona_prompt` 为空 且 `persona_lock` 为 false，THE Anima SHALL 维持改动前的默认行为不变。
