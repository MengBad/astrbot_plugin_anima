# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.5）整合两份审计的结论，修复高危功能"名不副实"与全系统可观测性/耦合缺陷。

**高危功能审计结论**（7 个 danger 功能 vs 各自设计理念）：

| 功能 | 现状 | 问题 |
| --- | --- | --- |
| `danger_stance_propagation` 立场传播 | ✅ 真落地 | 无 |
| `danger_relationship_inference` 关系推断 | ✅ 能跑 | 图谱推断了但只注入"当前对话者"一条，其余几乎不被消费 |
| `danger_core_mutation` 核心突变 | ✅ 能跑 | 把 LLM 输出**直接当 persona_core.yaml 写文件**，只查 `"用户主权"` 子串，**无 YAML 合法性校验** |
| `danger_active_info_collection` 主动信息收集 | ⚠️ 理念落空 | 生成欲望 `intensity=0.4`，而 stance 发言门槛 `>0.5`，**永远发不出口**，降级成短暂上下文提示 |
| `danger_memory_infection` 记忆感染 | ⚠️ 严重缩水 | "感染"理念是重复植入，实际只**一次性**发一条 outward 欲望后 `satisfied`，无重复/无追踪 |
| `danger_identity_crisis` 身份危机 | ⚠️ 靠天吃饭 | 稳定度下降**完全依赖 Sylanne 状态字段**，没装 Sylanne 则永不触发（死逻辑） |
| `danger_autonomous_web` 自主网络 | ⚠️ 喂垃圾 | `_fetch_url` 只取 `<p>` 前 20 段/500 字，搜索结果正文提取质量差；产出进能力系统 |

**能力闭环审计结论**（全系统 write→read→consume）：子系统闭环大体健康，但有三处横切缺陷：

1. **可观测性缺口**：多个内部 LLM 调用（反刍、矛盾检测、突变 type/mutation、autonomous_web 合成、能力执行/日记/规律总结）**没有 `_stat_bump("llm.*")` 埋点**，仪表盘低报内部 token 消耗。
2. **强耦合单点**：`active_info_collection` / `memory_infection` / `autonomous_web` 都挂在 `desire_enabled`；该开关一关，三个高危功能集体静默失效，但其各自开关仍显示"开"，产生误导。
3. **魔数不一致**：欲望 intensity 阈值在生成端（0.4）与发言端（0.5）打架，属配置层隐藏 bug。

本特性按"明确 bug → 理念落地/明确降级 → 解耦与可观测"分层修复。所有高危功能仍默认关闭。

## Glossary

- **高危功能 (Danger_Feature)**：`danger.py` 中受 `danger_*` 开关控制的 7 个功能，全部默认关闭。
- **立场传播 (Stance_Propagation)**：`_danger_stance_propagation`，把高强度 outward 欲望润色为主动发言。发言门槛 `intensity > 0.5`。
- **主动信息收集 (Active_Info_Collection)**：`_danger_active_info_collection`，生成"想问什么"的提问欲望。
- **记忆感染 (Memory_Infection)**：`_danger_memory_infection_check`，生成"想让对方记住"的欲望。
- **身份危机 (Identity_Crisis)**：`_danger_identity_crisis_*`，维护 `_identity_stability`（0–1），低于 0.5 注入游离感文本。
- **核心突变 (Core_Mutation)**：`_danger_core_mutation`，每 100 次沉淀改写 `persona_core.yaml`。
- **自主网络 (Autonomous_Web)**：`_danger_autonomous_web`，抓 Bing → 提炼成个人能力。
- **埋点 (Stat_Bump)**：`_stat_bump("llm.<purpose>")`，受 `dashboard_enabled` 控制，供仪表盘统计内部 LLM 调用。
- **发言门槛 (Stance_Threshold)**：`stance_propagation` 触发主动发言所需的最低 intensity（当前硬编码 0.5）。

## Requirements

### Requirement 1: 修复主动信息收集的阈值矛盾（P0 明确 bug）

**User Story:** 作为插件运维者，我希望"主动信息收集"要么真能把问题问出口、要么明确只作上下文提示，以便它的行为与开关名称一致、不再是个事实失效的开关。

#### Acceptance Criteria

1. THE Anima SHALL 提供配置项 `active_info_collection_can_speak`（bool，默认 `false`）。
2. WHERE `active_info_collection_can_speak` 为 `true`，THE Active_Info_Collection SHALL 以高于 Stance_Threshold 的 intensity（≥ 0.55）写入提问欲望，使其能被 Stance_Propagation 主动问出。
3. WHERE `active_info_collection_can_speak` 为 `false`，THE Active_Info_Collection SHALL 以低于 Stance_Threshold 的 intensity 写入提问欲望（仅作上下文注入，不主动发言，保持 v0.8.4 之后的现有保守行为）。
4. THE Anima SHALL 在该高危功能的配置 `hint` 中明确说明：默认仅作上下文暗示，开 `active_info_collection_can_speak` 才会主动发问。

### Requirement 2: 核心突变写入前 YAML 校验（P0 数据安全）

**User Story:** 作为插件运维者，我希望核心人格突变在写入 persona_core.yaml 前先校验合法性，以便畸形/截断的 LLM 输出不会污染核心文件。

#### Acceptance Criteria

1. WHEN Core_Mutation 得到 LLM 改写的核心内容，THE Anima SHALL 先尝试用 YAML 解析校验其为合法的 YAML 映射，再决定是否写入。
2. IF 改写内容 YAML 解析失败或不是映射结构，THEN THE Anima SHALL 放弃本次写入、保留原 `persona_core.yaml`、记录告警日志，不抛异常中断沉淀链。
3. THE Anima SHALL 保留既有的 `"用户主权"` 子串安全检查与 `.bak` 备份机制。
4. IF YAML 中缺失既有的关键顶层结构（至少包含 `core_beliefs`），THEN THE Anima SHALL 放弃本次写入并记录告警。

### Requirement 3: 记忆感染的重复与追踪机制（P1 理念落地）

**User Story:** 作为插件运维者，我希望记忆感染要么具备符合其理念的"重复强调 + 追踪是否被记住"机制、要么明确降级为单次强调并据实命名，以便其行为不再与"极高危"的名头脱节。

#### Acceptance Criteria

1. THE Memory_Infection SHALL 为其产生的欲望设置可被多次触发的语义：在该欲望未被满足前，允许 Stance_Propagation 在不同对话轮多次强调（不在首次发言后立即 `satisfied`）。
2. THE Anima SHALL 提供配置项 `memory_infection_max_repeats`（int，默认 `2`），限制同一条感染欲望被主动强调的最大次数。
3. WHEN 一条感染欲望被强调次数达到 `memory_infection_max_repeats`，THE Memory_Infection SHALL 将其标记为 `satisfied`，不再强调。
4. WHEN 检测到对方消息中出现该感染信息的关键词（复用既有 `_check_desire_satisfaction` 语义/关键词匹配），THE Memory_Infection SHALL 提前将该欲望标记为 `satisfied`（视为"已被记住"）。
5. THE Anima SHALL 在感染欲望数据中记录已强调次数字段（如 `repeat_count`）。

### Requirement 4: 身份危机的内生触发源（P2 解耦）

**User Story:** 作为没有安装 Sylanne 的用户，我希望身份危机功能也能基于 Anima 自身状态触发，以便它不再是一段永不执行的死逻辑。

#### Acceptance Criteria

1. WHEN Identity_Crisis 启用 且 `sylanne_state` 为空，THE Anima SHALL 基于自身内部信号评估身份稳定度。
2. WHERE 当前情绪评分（`last_emotion_score`）高于 0.85 且触及 `identity_denial` 伤痕维度，THE Anima SHALL 下调 `_identity_stability`。
3. WHERE 近期发生过核心突变（48 小时内有 `mutation_history` 条目），THE Anima SHALL 下调 `_identity_stability`。
4. THE Anima SHALL 保留既有的 Sylanne 状态驱动路径（装了 Sylanne 时两条信号源叠加）。
5. THE Anima SHALL 保留既有的 `+0.02`/轮自然恢复机制。

### Requirement 5: 自主网络抓取质量改进（P1）

**User Story:** 作为插件运维者，我希望自主网络抓取能提取到更有用的正文，以便合成的能力不是基于残缺信息。

#### Acceptance Criteria

1. THE Autonomous_Web 的 URL 抓取 SHALL 在 `<p>` 标签之外，同时提取 `<li>`、`<h1>`–`<h3>`、`<div>` 等常见正文标签的文本。
2. THE Autonomous_Web 的 URL 抓取 SHALL 过滤明显的导航/脚本噪音（`<script>`/`<style>` 内文本不计入）。
3. THE Autonomous_Web 的 URL 抓取 SHALL 将提取上限从 500 字符提高到可配置（`autonomous_web_extract_chars`，默认 `1500`）。
4. WHILE 抓取结果为空或全为噪音，THE Autonomous_Web SHALL 维持既有"记录失败、不合成能力"的降级行为。

### Requirement 6: 内部 LLM 调用可观测性补齐（能力闭环审计）

**User Story:** 作为关注成本的用户，我希望所有内部 LLM 调用都被仪表盘统计，以便 token 画面真实完整。

#### Acceptance Criteria

1. WHEN 离线反刍发起内部 LLM 调用，THE Anima SHALL 触发 `_stat_bump("llm.rumination")`。
2. WHEN 矛盾检测发起内部 LLM 调用，THE Anima SHALL 触发 `_stat_bump("llm.contradiction")`。
3. WHEN Core_Mutation 发起内部 LLM 调用（类型选择与改写各计），THE Anima SHALL 触发 `_stat_bump("llm.mutation")`。
4. WHEN Active_Info_Collection 发起内部 LLM 调用，THE Anima SHALL 触发 `_stat_bump("llm.info_collection")`。
5. WHEN Memory_Infection 发起内部 LLM 调用，THE Anima SHALL 触发 `_stat_bump("llm.memory_infection")`。
6. WHEN Autonomous_Web 的能力合成发起内部 LLM 调用，THE Anima SHALL 触发 `_stat_bump("llm.research_synthesis")`。
7. THE 新增埋点 SHALL 继续受 `dashboard_enabled` 总开关约束（关闭时 `_stat_bump` 自身跳过，无需额外处理）。

### Requirement 7: 高危功能依赖透明化（能力闭环审计）

**User Story:** 作为管理员，我希望明确知道哪些高危功能依赖 `desire_enabled`，以便不被"开关显示开、功能实际静默"误导。

#### Acceptance Criteria

1. THE Anima SHALL 在 `danger_active_info_collection`、`danger_memory_infection`、`danger_autonomous_web` 的配置 `hint` 中明确标注"需同时开启 `desire_enabled` 才生效"。
2. WHEN 这些功能因 `desire_enabled` 关闭而提前 return，THE Anima SHALL 在该功能开启但依赖未满足时输出一次性 debug 日志说明原因（不刷屏）。

### Requirement 8: 回归安全

**User Story:** 作为维护者，我希望本次改动有明确回归保护，以便确认既有行为不被破坏。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 236 个测试），THE Anima SHALL 使其全部通过。
2. THE Anima SHALL 新增测试覆盖：阈值矛盾修复、YAML 校验拒绝畸形输入、记忆感染重复/满足、身份危机内生触发、抓取多标签提取、新增埋点触发。
3. WHERE 所有高危功能保持默认关闭，THE Anima SHALL 维持改动前的默认行为不变。
