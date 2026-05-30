# Requirements Document

## Introduction

本特性（Anima 插件 **v1.0.0**）为运行仪表盘补上**历史趋势**——当前只有"今日"快照（跨天归零），无法判断 token 消耗是涨是跌、各子系统活跃度的变化趋势。同时作为 1.0.0 正式发布的里程碑，完成全面回归确认与文档定稿。

### 当前状态

- `StatsMixin._stat_bump` 把计数写入 `anima_state.json` 的 `stats_daily` 字段（`{"date":"YYYY-MM-DD","counts":{...}}`）。
- `_ensure_stats_loaded` 在跨天时**直接归零**——旧数据丢失，无法回溯。
- `/anima_stats` 和独立端口仪表盘只展示今日数据。

### 目标

- 跨天时把前一天的快照**归档**到 `stats_history`（持久化在 `anima_state.json`，上限可配）。
- `/anima_stats` 文本命令追加"近 7 天 LLM 调用趋势"摘要。
- 独立端口仪表盘新增 `/api/stats_history` 接口 + 前端趋势图（简单折线/柱状图，纯 JS 无新依赖）。
- 全量回归 339+ 测试通过。
- README 文档定稿（配置项完整性、部署指南、版本号 1.0.0）。

## Glossary

- **每日快照 (Daily_Snapshot)**：`{"date":"YYYY-MM-DD","counts":{...}}`，一天结束时的完整计数器。
- **历史归档 (Stats_History)**：`anima_state.json` 中新增的 `stats_history` 字段，存最近 N 天的 Daily_Snapshot 列表（按日期升序）。
- **历史保留天数 (History_Days)**：`dashboard_history_days`（int，默认 `30`），超出则丢弃最旧的。

## Requirements

### Requirement 1: 跨天归档

**User Story:** 作为插件运维者，我希望每天的运行统计被自动保存，以便回溯历史趋势。

#### Acceptance Criteria

1. WHEN `_ensure_stats_loaded` 检测到跨天（当前日期 != 已加载日期），THE StatsMixin SHALL 在归零前把旧的 Daily_Snapshot 追加到 `stats_history`。
2. THE `stats_history` SHALL 为一个按日期升序的 Daily_Snapshot 列表，持久化在 `anima_state.json`。
3. THE `stats_history` 长度 SHALL NOT 超过 `dashboard_history_days`（默认 30）；超出时丢弃最旧条目。
4. WHERE `dashboard_enabled` 为 `false`，THE StatsMixin SHALL NOT 归档（因为计数本身被跳过，归档空数据无意义）。
5. THE 归档逻辑 SHALL 在 `_ensure_stats_loaded` 内完成（不新增定时任务），利用"首次跨天访问"触发。

### Requirement 2: 历史数据读取

**User Story:** 作为插件运维者，我希望能通过命令和 API 查看历史趋势。

#### Acceptance Criteria

1. THE `_stats_snapshot()` SHALL 新增 `history` 字段，值为 `stats_history` 列表（最近 N 天的 Daily_Snapshot）。
2. THE `_render_stats()` SHALL 在文本末尾追加"近 7 天 LLM 调用趋势"摘要（每天一行：日期 + 总 LLM 调用数）。
3. THE 独立端口仪表盘 SHALL 新增 `/api/stats_history` 接口，返回 `{"success":true,"history":[...]}`（受 token 鉴权）。
4. WHERE `stats_history` 为空（首次使用或刚升级），THE 接口/命令 SHALL 返回空列表/提示"暂无历史数据"，不报错。

### Requirement 3: 前端趋势图

**User Story:** 作为插件运维者，我希望在仪表盘网页上看到直观的趋势图。

#### Acceptance Criteria

1. THE 运行仪表盘页面（`pages/dashboard/app.js`）SHALL 新增一个"历史趋势"区域，展示近 N 天的 LLM 总调用数折线/柱状图。
2. THE 前端 SHALL 通过 `apiGet('stats_history')` 获取数据，无数据时显示友好提示。
3. THE 图表 SHALL 用纯 JS + CSS 实现（Canvas 或 SVG 均可），不引入新的前端依赖。
4. THE 图表 SHALL 自适应暗色主题（沿用既有 dashboard 的 CSS 变量）。

### Requirement 4: 配置项

**User Story:** 作为插件运维者，我希望能控制历史保留天数。

#### Acceptance Criteria

1. THE Anima SHALL 提供配置项 `dashboard_history_days`（int，默认 `30`）。
2. THE 配置项 SHALL 在 `_conf_schema.json` 标注 ⚪ Token 无。

### Requirement 5: 全面回归与版本

**User Story:** 作为维护者，我希望 1.0.0 是一个稳定的正式发布。

#### Acceptance Criteria

1. WHEN 运行全部测试套件，THE Anima SHALL 使其全部通过（339 基线 + 本版新增）。
2. THE 版本号 SHALL bump 到 `1.0.0`（metadata.yaml + main.py @register）。
3. THE CHANGELOG SHALL 新增 v1.0.0 条目。
4. THE README SHALL 完成最终审校：版本徽章 1.0.0、配置项表完整（含 dashboard_history_days）、部署指南无遗漏。

## Correctness Properties

### Property 1: 归档不丢数据
*对任意*非空 Daily_Snapshot，跨天归档后 `stats_history` 的最后一条等于该快照（日期与 counts 完全一致）。

### Property 2: 历史上限裁剪
*对任意*已有 `stats_history` 长度与 `dashboard_history_days` 值，归档后 `len(stats_history) <= dashboard_history_days`，且被裁剪的是最旧条目。

### Property 3: 归档幂等（同一天不重复归档）
*对任意*调用序列，同一天内多次触发 `_ensure_stats_loaded` 不会重复归档同一天的快照。
