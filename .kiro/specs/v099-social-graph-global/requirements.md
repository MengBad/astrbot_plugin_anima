# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.9）细化 v0.9.8 的隔离粒度：**群环境按群隔离（保持），但"对人的认知"跨群统一**。

背景：v0.9.8 把整个 `worldview.json` 按 umo（群）隔离。但 worldview 内部其实有两类性质不同的数据：

- **群环境**（`environment` 环境氛围 / `norms` 群规范 / `my_position` 角色在群里的位置 / `external_knowledge` 该群联网知识）：这是"这个群是什么样"，**应按群隔离**（v0.9.8 已正确隔离）。
- **对人的认知**（`social_graph` 群友画像，按 user_id；`relationships` 关系图谱，按 "uid -> uid"）：这是"bot 认识谁、谁跟谁什么关系"。同一个人（如张三）出现在 A 群和 B 群时，bot 对他的认知**应该跨群统一**——而 v0.9.8 把它按群切开了，导致张三在 A 群和 B 群是两份独立画像。

用户场景确认："群环境按群分，但对某个人的认知应该跨群统一。"

本特性把 `social_graph` 与 `relationships` 从 per-umo worldview 中**抽出到一个全局存储**（按 user_id / 关系对 key，跨群共用一份），其余 worldview 字段保持按群隔离。世界观更新与关系推断写入时，分别落到"全局人物认知"与"会话群环境"两处；注入与读取时合并呈现。

## Glossary

- **群环境 (Group_Env)**：worldview 中的 `environment` / `norms` / `my_position` / `external_knowledge` / `last_updated` 等"群级"字段，按 umo 隔离。
- **人物认知 (Social_Knowledge)**：`social_graph`（dict，key=user_id）+ `relationships`（dict，key="uid -> uid"），跨群全局统一。
- **全局人物认知存储 (Social_Store)**：本特性新增的全局文件 `social_graph.json`，存 `{ "social_graph": {...}, "relationships": {...} }`，不按 umo 分。
- **会话世界观 (Session_Worldview)**：per-umo 的 `sessions/<umo>/worldview.json`，v0.9.9 后只存 Group_Env，不再存 Social_Knowledge。
- **世界观更新 (Worldview_Update)**：`_maybe_update_worldview`，LLM 整理对群的认知（含 environment 与 social_graph）。
- **关系推断写入 (Relationship_Write)**：`_apply_relationships_from_map`，把推断出的关系映射写入。
- **合并视图 (Merged_View)**：读取时把 Group_Env（按 umo）与 Social_Knowledge（全局）合并成完整 worldview dict，供既有消费逻辑透明使用。

## Requirements

### Requirement 1: 人物认知抽到全局存储

**User Story:** 作为使用者，我希望 bot 对某个人的认知跨群统一，以便同一个人在不同群被 bot 一致地认识。

#### Acceptance Criteria

1. THE Anima SHALL 提供全局 Social_Store（`social_graph.json`），存储 `social_graph`（key=user_id）与 `relationships`（key="uid -> uid"）两个映射，不按 umo 隔离。
2. THE Anima SHALL 提供 `_read_social_store()` / `_write_social_store(data)` 读写 Social_Store。
3. THE Social_Knowledge SHALL 在所有会话间共享同一份数据（A 群更新某人画像，B 群读取到相同画像）。
4. THE `relationships` SHALL 保留既有的最近 30 条上限裁剪。
5. THE `social_graph` SHALL 有最大条数上限 `social_graph_max`（int，默认 `100`），超出保留最近 N 条。

### Requirement 2: 群环境保持按群隔离

**User Story:** 作为使用者，我希望群氛围/群规这类群级认知仍按群独立，以便 A 群的环境认知不混进 B 群。

#### Acceptance Criteria

1. THE Session_Worldview SHALL 继续按 umo 隔离存储 Group_Env（`environment` / `norms` / `my_position` / `external_knowledge`）。
2. THE Session_Worldview SHALL NOT 再持久化 `social_graph` 与 `relationships`（这两项移交 Social_Store）。
3. WHERE 读取某 umo 的完整 worldview，THE Anima SHALL 返回 Merged_View（该 umo 的 Group_Env + 全局 Social_Knowledge 合并）。

### Requirement 3: 世界观更新分流写入

**User Story:** 作为开发者，我希望世界观更新时把群环境与人物认知分别落到正确的存储，以便两类数据各按其隔离粒度持久化。

#### Acceptance Criteria

1. WHEN Worldview_Update 从 LLM 得到含 `social_graph` 的结果，THE Anima SHALL 把 `social_graph` 合并写入全局 Social_Store，把 `environment`/`norms`/`my_position` 等写入该 umo 的 Session_Worldview。
2. WHEN Worldview_Update 注入 prompt 时展示已有画像，THE Anima SHALL 从全局 Social_Store 读取 `social_graph` 供 LLM 参考（保留既有截断 `worldview_graph_inject_cap` 防 prompt 爆炸）。
3. THE Worldview_Update 的 `social_graph` 合并写回逻辑（防止未传给 LLM 的旧画像丢失）SHALL 基于全局 Social_Store 的 full_graph 进行。

### Requirement 4: 关系推断写入全局

**User Story:** 作为开发者，我希望关系推断结果写入全局人物认知，以便关系图谱跨群统一。

#### Acceptance Criteria

1. WHEN Relationship_Write（`_apply_relationships_from_map`）写入关系映射，THE Anima SHALL 写入全局 Social_Store 的 `relationships`，不再写入 per-umo worldview。
2. THE Relationship_Write SHALL 保留既有 `_is_rejected` 过滤与 30 条上限。
3. THE Relationship_Write 的 umo 参数 SHALL 变为不再影响存储位置（全局唯一），但保留签名向后兼容（忽略或仅用于日志）。

### Requirement 5: 读取与注入合并

**User Story:** 作为开发者，我希望既有的 worldview 消费逻辑无需大改就能拿到"群环境 + 全局人物认知"的合并视图。

#### Acceptance Criteria

1. WHEN `_get_worldview_text(event)` 注入当前对话者画像，THE Anima SHALL 从全局 Social_Store 取该 sender 的 `social_graph` 条目（跨群统一）。
2. WHEN `_propagate_cross_relation_scar` 读取 `social_graph`，THE Anima SHALL 从全局 Social_Store 读取（跨群相似关系传播基于统一画像）。
3. THE Merged_View SHALL 保证既有读取 worldview 的代码（按 `.get("social_graph")` / `.get("relationships")` / `.get("environment")`）行为不变。

### Requirement 6: 向后兼容与迁移

**User Story:** 作为现有用户，我希望升级后历史的 social_graph/relationships 数据迁移到全局存储，以便不丢失已积累的人物认知。

#### Acceptance Criteria

1. WHEN 升级后首次访问 Social_Store 且其文件不存在，THE Anima SHALL 从旧的全局 `worldview.json` 以及各 `sessions/*/worldview.json` 中收集已有的 `social_graph`/`relationships` 合并为初始 Social_Store（一次性迁移，幂等）。
2. THE 迁移 SHALL 写入迁移标记，避免重复迁移。
3. THE 迁移 SHALL NOT 删除旧 worldview 文件中的 social_graph（保留即可，读取走合并视图后旧字段不再被消费）。
4. WHERE 迁移时多个会话对同一 user_id 有不同画像，THE Anima SHALL 以"最近更新优先/后写覆盖"的简单策略合并（不强求语义融合）。

### Requirement 7: 回归安全

**User Story:** 作为维护者，我希望本次粒度细化有明确回归保护。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 298 个测试），THE Anima SHALL 使其全部通过。
2. THE Anima SHALL 新增测试覆盖：Social_Store 全局读写、跨群统一（A 群写 social_graph，B 群读到）、群环境仍按群隔离、关系写入全局、合并视图、迁移幂等。
3. WHERE 单群场景，THE Anima SHALL 表现与 v0.9.8 等价（人物认知与群环境都只有一份）。
