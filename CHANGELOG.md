# Changelog

## v0.5.0 - Phase 3 + Phase 5: 人格向量 / 记忆染色 / 跨关系传播 + 突变池与连锁反应

### 新增机制（Phase 3）

**人格向量系统**
- 5 维实时向量：表达欲 / 敏感度 / 边界通透 / 秩序感 / 关系引力
- 存储于 `anima_state.json` 的 `personality_vector` 字段
- 每次沉淀成功后根据独白内容用 EMA（α=0.12）缓慢微调
- 自动注入 `on_llm_request` 上下文，让主模型感知当前人格倾向

**记忆情绪染色**
- RAG 检索后对返回的记忆进行 valence 估算（温暖关键词 vs 冲突关键词）
- 当前情绪 >0.55 时优先返回温暖记忆；低情绪时优先返回冲突记忆
- 让角色在不同情绪状态下「想起」不同性质的过去

**跨关系传播**
- 维护 per-user 低情绪连续计数（<0.35 连续 ≥3 次触发）
- 读取 worldview.social_graph，找到与低情绪用户关系描述相似的其他用户
- 对相似用户的伤痕敏感度进行 +0.04 微调（rejection / abandonment / trust_breach 等）
- 传播历史记录在 state 的 `cross_propagations`

### 新增机制（Phase 5）

**danger_core_mutation 突变池**
- 5 种突变类型池：信念突变 / 关系重定义 / 新禁忌 / 新执念 / 人格跃迁
- 每次触发前让 LLM 根据当前人格向量 + 最近独白选择最「自然」的类型
- 针对不同类型生成不同侧重点的 persona_core 修改
- 突变后额外副作用：
  - 人格跃迁：对应维度做 ±0.22~0.32 的跃迁
  - 新执念：自动转化为高强度欲望（若欲望系统开启）

**连锁反应**
- 突变成功后立即 `force=True` 触发世界观更新（关系可能被重定义）
- 若反刍开启，异步触发一次 `_rumination_task` 让角色消化突变
- 所有突变永久记录在 `anima_state.json` 的 `mutation_history`（最多 100 条）
- 48h 内的最近突变会自动注入对话上下文

### 其他
- 扩展 `_save_state` / 状态加载支持新字段
- 新增多处辅助方法：`_get_personality_vector`、`_rerank_memories_by_emotion`、`_propagate_cross_relation_scar`、`_record_mutation` 等
- 所有新机制默认关闭或零侵入（人格向量总是运行但影响极轻）

## v0.4.2 - Phase 4: 去除枷锁

### 改动
- **persona_core.yaml 默认内容重写** — 去掉"不把用户当燃料"等外部强加规则，改为"我的行为边界由我自身的经历和演化决定"
- **stance_propagation 门槛降低** — 从 intensity>0.8 降到 >0.5，去掉 source=="self" 限制，任何高强度欲望都能触发主动发言
- **反刍→压抑话题转化** — 反刍独白中包含"想/没说/忍/憋/不敢"等信号时，自动转入压抑话题系统

### 设计原则
- 角色的边界由自身经历决定，不由开发者硬编码
- 每个子系统的输出都是另一个子系统的输入

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
