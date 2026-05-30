# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.6）补齐前序版本"已立项但未实现"的卫生项，并修复生产日志暴露的明确性能问题。目标是把反馈/欲望/世界观/压抑矛盾这几个 🟡 维度各推高 1–2 分。

涵盖问题（来自 v0.9.5 残留 spec + 生产日志诊断）：

1. **跨关系传播每轮触发（性能黑洞）**：生产日志显示几乎每条消息后都打印"跨关系传播触发"。根因：`_update_user_low_emotion_streak` 的低情绪判定 `score < 0.35` 对日常闲聊过宽（闲聊情绪本就 0.0–0.25），连续 3 次即触发。导致每轮都跑一次 `_propagate_cross_relation_scar`（读写 worldview + state）。
2. **反馈 accepted 阈值过松**：`_evaluate_feedback` 中 `sim >= 0.30` 判 accepted，且中间区段（0.10–0.30）也判 accepted。日常对话延续相似度普遍 > 0.30，导致几乎每条都判 accepted，反馈信号失真。
3. **压抑话题/矛盾无语义去重**：`_add_suppressed_topic` 与矛盾写入都直接 append，同一件事以不同措辞反复堆积。
4. **矛盾记录无上限**：`contradictions.json` 是全项目唯一无裁剪的持久化集合，长期膨胀且每次沉淀全量读写。
5. **工具学习记录无上限**：`tool_learning.json` 的 `records` 列表无界增长。
6. **embedding 可用性无自检**：`_embed_one` 靠猜方法名调用，框架改名会静默降级到 Jaccard，无可观测性。

所有改动为局部、低风险，不引入新子系统、不改变默认启用的功能集。

## Glossary

- **跨关系传播 (Cross_Relation_Propagation)**：`_propagate_cross_relation_scar`，某用户连续低情绪时微调 social_graph 中相似关系用户的伤痕敏感度。
- **低情绪连续计数 (Low_Emotion_Streak)**：`_update_user_low_emotion_streak` 维护的 per-user 连续低情绪次数，达阈值触发跨关系传播。
- **反馈评估 (Feedback_Eval)**：`_evaluate_feedback`，判定用户对角色上次发言的反馈为 accepted/ignored/rejected/none。
- **压抑话题 (Suppressed_Topic)**：`suppressed_topics.json` 中"想说没说"的事，上限 20 条。
- **矛盾记录 (Contradiction_Record)**：`contradictions.json` 中的自我矛盾条目，当前无上限。
- **工具学习记录 (Tool_Records)**：`tool_learning.json` 的 `records` 列表。
- **文本相似度 (Text_Similarity)**：`capability_dedup.text_similarity`，字符 2-gram Jaccard，0–1。
- **embedding 可用性 (Embedding_Availability)**：`_embed_one` 能否真正调通 embedding provider 并返回向量。

## Requirements

### Requirement 1: 跨关系传播触发收紧（性能）

**User Story:** 作为插件运维者，我希望跨关系传播不再被日常闲聊每轮触发，以便消除日志已证实的性能黑洞。

#### Acceptance Criteria

1. THE Low_Emotion_Streak SHALL 使用可配置的低情绪阈值 `cross_relation_low_emotion_threshold`（float，默认 `0.2`），仅当情绪评分低于该阈值时累加连续计数。
2. THE Low_Emotion_Streak SHALL 使用可配置的连续次数门槛 `cross_relation_streak_threshold`（int，默认 `5`），仅当连续低情绪次数达到该门槛时触发 Cross_Relation_Propagation。
3. WHEN 情绪评分不低于 `cross_relation_low_emotion_threshold`，THE Low_Emotion_Streak SHALL 将该用户的连续计数清零。
4. THE Cross_Relation_Propagation SHALL 保留既有的相似关系匹配与 +0.04 微调逻辑不变（仅改触发频率，不改传播效果）。

### Requirement 2: 反馈 accepted 阈值收紧（信号质量）

**User Story:** 作为插件运维者，我希望反馈判定不再把所有对话延续都当成 accepted，以便反馈信号真实反映用户态度。

#### Acceptance Criteria

1. THE Feedback_Eval SHALL 使用可配置的 accepted 相似度阈值 `feedback_accepted_threshold`（float，默认 `0.45`），相似度不低于该值才判 accepted。
2. THE Feedback_Eval SHALL 使用可配置的 ignored 相似度阈值 `feedback_ignored_threshold`（float，默认 `0.15`），相似度低于该值判 ignored。
3. WHILE 相似度处于 ignored 与 accepted 阈值之间，THE Feedback_Eval SHALL 判定为 `none`（中性，不强化也不惩罚），不再保守判 accepted。
4. THE Feedback_Eval SHALL 保留既有的明确否定词优先判 rejected 逻辑不变。

### Requirement 3: 压抑话题语义去重

**User Story:** 作为插件运维者，我希望压抑话题加入前做相似度去重，以便同一件事不以不同措辞反复堆积。

#### Acceptance Criteria

1. WHEN 新增一条 Suppressed_Topic，THE Capability SHALL 先与现有未解决话题逐一做 Text_Similarity 比较。
2. IF 与某条现有未解决话题的相似度不低于 `dedup_text_threshold`（float，默认 `0.7`），THEN THE Capability SHALL 不新增该话题（视为重复）。
3. THE 去重 SHALL 复用 `capability_dedup.text_similarity`，不调用 LLM。
4. THE 去重 SHALL NOT 影响压力递增、释放检查、上限 20 条等既有行为。

### Requirement 4: 矛盾记录语义去重 + 上限裁剪

**User Story:** 作为插件运维者，我希望矛盾记录去重并有上限，以便它不重复堆积也不无限膨胀。

#### Acceptance Criteria

1. WHEN 检测到新矛盾准备写入，THE Capability SHALL 先与近期已记录矛盾做 Text_Similarity 比较，相似度不低于 `dedup_text_threshold` 时不重复记录。
2. THE Contradiction_Record 集合 SHALL 有最大条数上限 `contradiction_max`（int，默认 `50`）。
3. WHEN 写入矛盾记录后超过上限，THE Capability SHALL 仅保留最近的上限条数。
4. THE 上限裁剪 SHALL 与既有 relationships(30)/suppressed(20)/mutation_history(100) 的裁剪风格一致。

### Requirement 5: 工具学习记录上限裁剪

**User Story:** 作为插件运维者，我希望工具学习记录有上限，以便它不无界增长。

#### Acceptance Criteria

1. THE Tool_Records 列表 SHALL 有最大条数上限 `tool_records_max`（int，默认 `200`）。
2. WHEN 追加记录后超过上限，THE Capability SHALL 仅保留最近的上限条数。
3. THE 裁剪 SHALL NOT 影响 `_summarize_tool_rules` 读取最近记录与按工具过滤的行为。

### Requirement 6: embedding 可用性自检

**User Story:** 作为插件运维者，我希望启动时能看到 embedding 是否真正可用，以便相似度精度静默降级时我能察觉。

#### Acceptance Criteria

1. WHEN 插件初始化 且 配置了 `embedding_provider_id`，THE Capability SHALL 执行一次 embedding 可用性自检并记录结果日志。
2. IF 自检失败（接口不可调用或返回非向量），THEN THE Capability SHALL 记录明确告警，说明将回退到 Jaccard。
3. THE 自检 SHALL NOT 阻塞初始化，失败不抛异常影响主流程。
4. WHERE 未配置 `embedding_provider_id`，THE Capability SHALL 跳过自检并记录信息日志。

### Requirement 7: 回归安全

**User Story:** 作为维护者，我希望本次改动有明确回归保护。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 259 个测试），THE Capability SHALL 使其全部通过。
2. THE Capability SHALL 为每项修复新增测试（streak 阈值、反馈三段判定、压抑去重、矛盾去重+上限、工具记录上限、embedding 自检）。
3. THE 新增配置项 SHALL 全部有合理默认值，保证未配置时行为可预期。
