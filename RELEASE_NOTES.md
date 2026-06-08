# Release Notes - v1.2.5

## 概要

v1.2.5 是 `astrbot_plugin_anima` 的一个认知观测性与稳定性加固版本。
本版本重点是对认知观测台（Cognitive Observatory）进行了深度加固与安全透视支持，而非修改角色的核心认知行为：

- 更加安全的状态落盘与原子写入
- 更健壮的插件卸载清理逻辑
- 一致的 Sylanne 响应观察机制
- 兼容低风险的 JSON 序列化 monkeypatch
- 新增认知观测台的 6 大细分脱敏诊断 API（Prompt、State、Memory、Desire、Scar、Personality Drift）
- 细化对内存检索证据（Memory Recall Replay）与欲望演化轨迹（Desire Evolution History）的脱敏展示
- 新增脱敏决策路径分析（Reasoning Trace）与会话序列还原（Session Replay）
- 重构并提供单一、规整的 AstrBot 插件 WebUI Portal 面板，并对旧页面资产进行向后兼容适配

本版本完全保留了双引擎架构：
- 遗留的 Anima Mixin 路径与接口保持可用
- Sylanne Alpha 热路径正常运行
- 没有任何高风险的自主性逻辑被简化或删除

## 核心亮点

- **原子化数据写入**：JSON 和文本写入机制采用临时文件写入、flush/fsync 后 `os.replace` 原子替换，彻底规避高频持久化时的文件损坏风险。
- **防止状态损坏覆盖**：当遇到 JSONDecodeError 时，不再用 `{}` 覆盖 state 损坏文件，而是备份为 `.bak` 方便排查。
- **收紧 `desires.json` 事务边界**：欲望衰减与满足逻辑迁移至单锁读改写事务机制。
- **Sylanne 响应捕捉完整化**：即使关闭了实时拦截，机器人的回复内容也会在后台进入 Sylanne 缓冲队列，确保记忆流一致性。
- **Idempotent Monkeypatch**：全局 JSON 编码器 monkeypatch 提升为幂等性保护，并在插件 terminate 时安全恢复。
- **独立及共享 WebUI 路由注册**：新诊断 API 同步注册在共享 AstrBot 端口与独立 Sylanne WebUI 服务器上。
- **脱敏 Prompt 调试器 (`/api/prompt_debug`)**：记录注入槽位名、预算上限及字符长度，绝对不暴露 Prompt 文本与记忆原文。
- **状态检查器 (`/api/state_inspector`)**：诊断活动会话状态、脏标志、持久化文件大小和隔离违规计数，展示状态拓扑而不读取核心人设与欲望。
- **记忆浏览器 (`/api/memory_explorer`)**：提供 L1/L2/L3 拓扑指标与 Consolidation 配置分析，不暴露具体记忆内容，仅提供 SHA-256 混淆指纹。
- **内存检索回放 (`/api/memory_recall_replay`)**：记录 L2 回收条目指纹与匹配分，不泄漏任何 Query 及 Prompt 详情。
- **欲望仪表盘 (`/api/desire_dashboard`)**：评估欲望队列健康度与极性分布，剔除欲望正文及目标 UMO/用户标识。
- **欲望演化历史 (`/api/desire_evolution`)**：回溯欲望周期，记录增删欲望的计数与指纹差异。
- **创伤浏览器 (`/api/scar_explorer`)**：跟踪 Scar Algebra 维度敏感度、愈合阶段与熔断器，剥离创伤事件原文。
- **人格漂移观测器 (`/api/personality_drift`)**：展现 5D 向量变动、表面特质 EMA 和人设 beliefs Fingerprint，屏蔽 persona_core 原始内容。
- **决策路径分析 (`/api/reasoning_trace`)**：串联 Prompt 注入、工具使用（记录输入/输出长度与成功状态）及响应事件，不保留工具参数值与回复文本。
- **会话回放仿真 (`/api/session_replay`)**：提取历史消息的气泡长度、发送方角色与发送时间，供时间线回放，绝不暴露真实聊天信息。
- **整合 Plugin Page 列表**：AstrBot 插件菜单精简为单一的 `Anima` 入口，旧页面无缝折叠入 Portal iframe 中以保证完美向后兼容。

## 兼容性说明

本次升级不需要任何数据迁移。
所有既有持久化文件均保持完全兼容：
- `anima_state.json`
- `self_notes.md`
- `desires.json`
- Sylanne `.alpha.json` 会话缓存
- AstrBot 数据库 KV 状态

如果系统检测到损坏 of JSON，会自动生成时间戳备份文件 `.bak`。

## 发版建议

- 建议 tag：`v1.2.5`
- 建议发布类型：补丁版本（Patch Release）
- 发版理由：在完全向后兼容的基础上，提供了极为强大的安全脱敏认知观测视图（Cognitive Observatory），保障插件生产环境稳定性。
