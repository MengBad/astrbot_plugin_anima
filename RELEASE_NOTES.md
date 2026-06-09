# Release Notes - v1.2.6

## 概要

v1.2.6 是 `astrbot_plugin_anima` 的一个可观测性与稳定性加固版本。
本版本重点引入了后台异步任务监控（Background Task Observatory）和状态数据源审计（StateStore Audit），并彻底修复了通过共享路由（AstrBot 插件管理页面）访问时的 WebUI 数据加载及卡片显示问题：

- 异步后台任务生命周期监控与统一容器管理
- 状态存储源（StateStore）只读一致性审计与元数据指纹机制
- AstrBot 共享 WebUI 路由完全修复与 API 动态映射
- 决策路径分析与会话回放的安全脱敏保护加固
- 全面的 `README.md` 中文文档重构与架构厘清

本版本完全保留了双引擎架构，不修改任何高风险的自主认知或演化逻辑，整体向后兼容。

## 核心亮点

- **后台任务监控台 (Background Task Observatory)**：通过 `/api/background_tasks` 接口，脱敏暴露活跃 asyncio 任务、时间碎片定时器、分段响应任务、Checkpoint 任务和投递队列的生命周期与队列深度，绝不泄漏回复正文和敏感 Context 键。
- **状态存储只读审计 (StateStore Audit)**：新增只读的 `/api/state_store_audit` 接口，盘点 `anima_state.json`、`self_notes.md`、`desires.json` 等全部数据源的可达性与文件大小，并基于元数据生成 `metadata_fingerprint` 与全局唯一 `source_fingerprint`，作为未来 diff 观测的基线。不读取或哈希文件正文，防隐私泄漏。
- **共享路由数据路径完全修复**：Portal API 与 iframe URL 引入 `routePath()` 助手，动态适配 AstrBot 共享页面（`/astrbot_plugin_anima/api/...`）与独立 WebUI 端口。
- **静态资源共享层绑定**：将遗留的 dashboard/capability-tree 页面资产、静态资源和人格回滚接口注册至 AstrBot 共享 WebUI 层，解决 Portal 嵌入卡片在共享页面中加载失败的问题。
- **人格回滚与突变历史加固**：回滚接口复用插件 IO 锁和原子文本写入，在共享与独立路由上记录一致的脱敏 `回滚恢复` 演化日志。抹除突变历史的 core-beliefs 具体细节，仅暴露哈希指纹。
- **决策路径与会话回放扩展**：支持 `state.store_audit_snapshot` 诊断快照事件流，并在 Timeline 中以元数据形式安全呈现。收紧了 Reasoning Trace 通用事件回退机制的白名单限制，防止意外泄漏复杂嵌套对象。
- **任务容器安全重构**：统一内部 `_background_tasks` 容器为 Set 结构，防止由于 API 变动在插件运行、派发、Takeover 和 Shutdown 时发生集合分歧或产生垃圾泄漏。
- **README 全面重写**：重写了项目中文说明文档，提供清晰的数据流图、首选配置、安全观测边界、部署及测试运行指引。

## 兼容性说明

本次升级不需要任何数据迁移。
所有既有持久化文件均保持完全兼容：
- `anima_state.json`
- `self_notes.md`
- `desires.json`
- Sylanne `.alpha.json` 会话缓存
- AstrBot 数据库 KV 状态

## 发版建议

- 建议 tag：`v1.2.6`
- 建议发布类型：补丁版本（Patch Release）
- 发版理由：在完全向后兼容的基础上，补齐了后台异步任务与数据一致性的安全透视，彻底修复了共享管理页面下的显示缺陷，强烈推荐所有使用 Portal 管理面板的 operator 升级。
