# Requirements Document

## Introduction

本特性（Anima 插件 v0.9.8）按**方案 1**实现会话级状态隔离：**角色本体人格全局共享，会话上下文按 umo（unified_msg_origin，即每个群/私聊会话）隔离**。

背景：当前所有持久化文件平铺在 `data/plugin_data/astrbot_plugin_anima/` 下，全局共享。`desires`（字段级 `target_umo` 过滤）与 `_outgoing_by_umo`（内存）已做 umo 区分，但 **`worldview.json`（群环境认知/关系图谱）和 `time_sense.json`（互动频率）是全局共享的**——导致 A 群的群友关系图谱、互动记录会混进 B 群，跨群污染。生产日志亦观察到世界观/时间感跨群混用。

方案 1 的隔离边界：

- **A 类（角色本体人格）—— 保持全局共享，不隔离**：`self_notes.md`、`persona_core.yaml`、`anima_state.json` 的 `personality_vector` / `last_emotion_score` / `identity_stability`、`scar_dimensions.json`、`personal_capabilities.json`。理由：这些代表"角色是谁"，跨群应是同一个人格，隔离会把同一 bot 撕裂成多重人格。
- **B 类（会话上下文）—— 按 umo 隔离**：`worldview.json`、`time_sense.json`。理由：群环境认知、互动频率是"这个群里发生了什么"，不应跨群混用。
- **已隔离，不动**：`desires.json`（字段级 `target_umo`）、`_outgoing_by_umo`（内存 per-umo）。

隔离实现采用**按 umo 派生子目录 + 全局文件回退**：每个 umo 的会话状态存到 `sessions/<安全化umo>/` 子目录；首次读取某 umo 且其子目录文件不存在时，回退读取旧的全局文件（向后兼容，老数据不丢、平滑迁移）。

## Glossary

- **umo (Unified_Msg_Origin)**：`event.unified_msg_origin`，AstrBot 对每个会话（群/私聊）的唯一标识。经 `_get_event_umo(event)` 获取。
- **会话上下文状态 (Session_State)**：按 umo 隔离的状态，本特性范围为 `worldview.json` 与 `time_sense.json`。
- **角色本体状态 (Persona_State)**：全局共享、不隔离的状态（self_notes / persona_core / personality_vector / scars / capabilities / identity_stability）。
- **会话目录 (Session_Dir)**：`data/plugin_data/astrbot_plugin_anima/sessions/<safe_umo>/`，存放某 umo 的会话上下文文件。
- **umo 安全化 (Safe_Umo)**：把 umo 字符串转成可作目录名的安全形式（替换非法路径字符），避免路径穿越。
- **全局回退 (Global_Fallback)**：当某 umo 的会话文件不存在时，读取旧的全局 `worldview.json` / `time_sense.json` 作为初始值（向后兼容）。
- **无 event 路径 (Eventless_Path)**：后台任务（如跨关系传播 `_propagate_cross_relation_scar` 经 create_task、离线反刍）无当前 event，需通过显式传入 umo 或回退到 `_last_active_umo`。

## Requirements

### Requirement 1: 会话目录派生与 umo 安全化

**User Story:** 作为插件运维者，我希望每个会话的上下文状态存到该会话专属目录，以便不同群的数据物理隔离。

#### Acceptance Criteria

1. THE Anima SHALL 提供 `_safe_umo(umo)` 方法，把 umo 字符串转成仅含安全字符（字母/数字/下划线/连字符）的目录名，对空 umo 返回固定的 `_default_`。
2. THE Anima SHALL 提供 `_session_dir(umo)` 方法，返回 `data_dir/sessions/<safe_umo>/` 路径并确保目录存在。
3. THE Safe_Umo SHALL 防止路径穿越（不含 `..`、`/`、`\` 等），不同的原始 umo SHALL 映射到不同的安全目录（碰撞时用哈希后缀消歧）。
4. THE Anima SHALL 提供 `_session_path(umo, filename)` 方法，返回某 umo 会话目录下指定文件的完整路径。

### Requirement 2: worldview 按 umo 隔离

**User Story:** 作为使用者，我希望每个群的世界观（环境/关系图谱）独立，以便 A 群的群友关系不混进 B 群。

#### Acceptance Criteria

1. THE Anima SHALL 让 `_read_worldview` 与 `_write_worldview` 接受一个 umo 参数（可选，默认空表示用全局/当前活跃 umo）。
2. WHEN 读取某 umo 的 worldview 且其会话文件存在，THE Anima SHALL 读取该会话文件。
3. WHEN 读取某 umo 的 worldview 且其会话文件不存在 但 全局 `worldview.json` 存在，THE Anima SHALL 读取全局文件作为回退（Global_Fallback）。
4. WHEN 写入某 umo 的 worldview，THE Anima SHALL 写入该 umo 的会话文件，不写全局文件。
5. WHERE worldview 的所有读写调用点（worldview.py / merged_eval.py / danger.py / relations.py）能取得 umo（来自 event 或显式传入），THE Anima SHALL 传入对应 umo。
6. WHERE Eventless_Path 无法取得 umo，THE Anima SHALL 回退到 `_last_active_umo`；若其也为空，THE Anima SHALL 使用 `_default_` 会话。

### Requirement 3: time_sense 按 umo 隔离

**User Story:** 作为使用者，我希望每个群的互动频率/时间感独立，以便"很久没见某人"的判断不跨群串扰。

#### Acceptance Criteria

1. THE Anima SHALL 让 `_read_time_sense` 与 `_write_time_sense` 接受一个 umo 参数。
2. WHEN `_update_time_sense(event)` 与 `_get_time_sense_text(event)` 运行，THE Anima SHALL 用 `event` 的 umo 读写对应会话的 time_sense。
3. THE time_sense 的会话文件 SHALL 沿用既有数据结构（last_interaction / interaction_frequency / interaction_timestamps / session_start / total_messages_today）。
4. WHEN 某 umo 首次访问 time_sense 且会话文件不存在 但 全局 `time_sense.json` 存在，THE Anima SHALL 读取全局文件作为回退。

### Requirement 4: 角色本体状态保持全局（不隔离）

**User Story:** 作为使用者，我希望角色跨群是同一个人格，以便它不会在不同群变成多重人格。

#### Acceptance Criteria

1. THE Anima SHALL NOT 隔离 `self_notes.md`、`persona_core.yaml`、`scar_dimensions.json`、`personal_capabilities.json`。
2. THE Anima SHALL NOT 隔离 `anima_state.json` 的 `personality_vector` / `last_emotion_score` / `identity_stability`。
3. THE Persona_State 的读写函数 SHALL 维持改动前的全局行为不变。

### Requirement 5: 向后兼容与无数据丢失

**User Story:** 作为现有用户，我希望升级后历史世界观/时间感数据不丢失，以便平滑过渡。

#### Acceptance Criteria

1. WHEN 升级后某 umo 首次读取 worldview/time_sense，THE Anima SHALL 通过 Global_Fallback 读到历史全局数据（不为空）。
2. THE Anima SHALL NOT 删除旧的全局 `worldview.json` / `time_sense.json`（保留作为回退源，避免破坏未迁移会话）。
3. WHERE 旧版本无会话目录，THE Anima SHALL 在首次写入时自动创建 `sessions/<safe_umo>/`。
4. THE 隔离改造 SHALL NOT 影响 desires（字段级 umo）与 _outgoing_by_umo（内存）的既有行为。

### Requirement 6: 回归安全

**User Story:** 作为维护者，我希望本次架构改动有明确回归保护。

#### Acceptance Criteria

1. WHEN 运行既有测试套件（改动前的全部 287 个测试），THE Anima SHALL 使其全部通过。
2. THE Anima SHALL 新增测试覆盖：umo 安全化（含路径穿越防护与碰撞消歧）、会话目录派生、worldview/time_sense 的 per-umo 读写与全局回退、跨 umo 隔离（A 群写不影响 B 群读）、角色本体状态仍全局。
3. WHERE 仅单个会话使用（单群场景），THE Anima SHALL 表现与改动前等价（行为不回归）。
