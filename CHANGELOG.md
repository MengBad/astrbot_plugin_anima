# Changelog

## v0.4.1 - Phase 2: 压抑话题 / 伤痕维度 / 反馈闭环

### 新增机制

**压抑话题系统**
- 角色想说但没说的话会积累压力（每小时 +0.05）
- 压力超过 0.8 时注入到对话上下文："你一直想说但没说出口的事"
- 角色说出来后压力释放，话题标记为 resolved
- 来源：被忽略的发言、未执行的欲望、反刍中的未表达想法

**伤痕维度**
- 5 个维度：abandonment / identity_denial / trust_breach / rejection / being_replaced
- 每次受伤 sensitivity +0.2（上限 3.0）
- 情绪评分乘以 sensitivity 系数（伤痕越深，同类事件情绪反应越强）
- 超过 7 天未触发的伤痕缓慢愈合（sensitivity -0.1/周）
- 极高情绪（>0.9）自动在对应维度产生新伤痕

**反馈闭环**
- 角色每次发言后启动 5 分钟观察窗口
- 用户回应内容 → accepted（增强该话题权重）
- 用户说不相关的话 → ignored（转入压抑话题）
- 用户明确否定 → rejected（产生 rejection 伤痕）

### 改进
- 沉淀流程开头自动更新压抑话题压力和伤痕衰减
- 情绪评分被伤痕维度放大后记录到日志

## v0.4.0 - Phase 1: 基础闭环修复

- 状态全面持久化（anima_state.json）
- 矛盾反哺行为（注入到对话上下文）
- 情绪评分注入对话（主模型感知情绪强度）
- 反刍产生欲望（离线反思触发新的行动意图）
- 独白去审查（只检查空内容）
- 欲望门槛降低（0.5 → 0.3）

## v0.3.6 - 自主网络行动重写

- autonomous_web 改用 aiohttp + Bing 搜索
- 移除 MCP 工具依赖
- 新增 _fetch_url 方法

## v0.3.5 - 高危功能安全修复

- stance_propagation 改用 llm_generate
- autonomous_web 改用 fetch 白名单
- ToolSet 空检查改用 .empty()

## v0.3.4 - 逻辑自检修复

- 离线反刍移除 umo 前置检查
- 身份危机修复大小写匹配

## v0.3.3 - 完善 core_mutation

- 初始化 persona_core.yaml
- on_llm_request 注入 persona_core
- 安全检查：用户主权不可删除
- /anima_core 指令

## v0.3.1 - 敏感内容过滤加固

- 新增 _is_sensitive 方法
- 全链路过滤（self_notes/evolution_log/向量检索/发言/搜索结果）

## v0.3.0 - 第三版功能完整

- 矛盾检测 / 离线反刍 / 溯源查询
- 高危功能层（8 个开关）
- 工具自学习
- 多模型支持（internal_provider_id / worldview_provider_id）

## v0.2.x - 第二版

- 欲望系统 / 世界观系统 / 时间感 / 自然遗忘
- WebUI 编辑器 / 拒绝语过滤 / 存储限流
- Sylanne 状态读取

## v0.1.0 - 初版

- 情绪触发沉淀 / self_notes 注入 / 向量记忆
- 演化日志 / 自动压缩
