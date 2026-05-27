# Changelog

## v0.6.1 - 紧急防爆炸：自主研究节流 + 能力去重 + 动态工具配额

针对 v0.6.0 实测中观察到的"单次对话产出 12+ 条同质能力 + 全部注册成独立 LLM 工具"问题做的紧急修复。建议所有 v0.6.0 用户升级。

### 三处修复
- **`_initiate_self_directed_research` 节流**：同一 reason（按 reason 关键字归一化、忽略其中的 user_id 数字）5 分钟内只允许触发一次；新增全局 `asyncio.Semaphore(1)` 保证同时只跑 1 个研究任务。修掉了 social_graph 里有几十个 user_id 时同时触发几十个并行研究的灾难。
- **能力名归一化匹配（去重）**：`_create_or_update_capability` 现在用关键词集合相似度找近似已有能力，命中 ≥2 个特征关键词且占新能力签名 ≥40% 时合并而不是新建。LLM 同义词（ego/self/我、anchor/锚、blade/axe/戉/兵戈）在去重前先归一化，防止"鸣戈守界 / EgoBladeDissector / 戉刃重构"这种本质同一的能力被反复创建。
- **动态工具注册每日配额**：新增 `dynamic_tool_daily_quota` 配置（默认 3）。超过配额的能力照常入库，但不再注册为独立 LLM 工具——避免 LLM 工具列表无限膨胀拖慢推理。工具名归一化也升级，纯中文名不再生成 `my_________` 这样无意义的下划线串。

### 配置新增
- `dynamic_tool_daily_quota` (int, default 3)：每日动态注册独立工具的硬上限

### 升级建议
推荐配置（编辑 AstrBot WebUI → Anima 配置）：
- `autonomy_research_on_time_absence`: 视场景，群多人时建议 false
- `dynamic_tool_daily_quota`: 3（保守）或更高
- 之前已经积累的能力库不会被自动清理；可以等 `_maintain_capabilities_health` 自动合并，或 `/anima_reset` 后从头来

## v0.6.0 - 完全自主存在：自我创造工具 + 独立研究学习闭环 + 框架兼容性大修

### 框架兼容性修复（必须升级原因）
- **修复 `@register` 装饰器缺失**：插件加载时不再需要手动放进 `data/plugins/`，可以直接 WebUI 上传 zip
- **修复 `_conf_schema.json` 解析错误**：清掉非法 `_comment` 字段和重复键，AstrBot ≥4.25 加载正常
- **修复 `__init__` 中 `asyncio.get_event_loop()` 在 Python 3.12 崩溃**：定时任务搬到 `async def initialize()` 钩子里
- **修复 `@filter.on_using_llm_tool` / `@filter.on_llm_tool_respond` 钩子签名错误**：补 `event` 第一参数
- **修复 `_get_provider_id(None)` 直接 AttributeError**：event 改 Optional，多级兜底
- **删除调用了不存在 API（`add_web_route` / `register_web_route`）的死代码**

### 健壮性升级
- **全局 IO 锁 + 原子 state 读改写封装**（`_atomic_update_state`）：消除并发写入丢更新与 JSONL 半行损坏
- **关键 IO 路径全部加 try/except OSError**：磁盘满或权限问题不再让插件初始化崩
- **`_is_sensitive` 改用单词边界正则**：不再误把 author/keyboard/secretary/tokenize/credentials 当敏感词
- **反馈窗口按 umo 隔离**：多群/多用户场景下反馈不再串台
- **`_initiate_self_directed_research(force=True)` 也尊重 autonomy_enabled 总开关**：用户主权优先
- **`_maintain_capabilities_health` 重写**：合并相似能力时 usage_count 不再丢更新；仅降权也会持久化
- **`/anima_capabilities` 支持分页**：避免 QQ 协议端单条转发消息超长导致发送失败

### v0.6 新增功能（核心）
- **个人能力系统（Personal Capabilities）**：角色现在可以「自己学会 + 自己创造 + 自己保存 + 自己修正」工具和方法
  - 数据文件 `personal_capabilities.json` + `capabilities_diary.md`
  - 每次自主研究成功后，LLM 帮角色把成果结构化成「个人工具卡」（含 description / how_to_use / parameters_schema / executable_snippet / should_register_as_tool）
  - 这些工具以高优先级注入到对话上下文
- **自主研究 → 能力创造闭环**：`_initiate_self_directed_research`（内部驱动）+ `_danger_autonomous_web`（外部触发）双路径
- **自我修正机制（结构化 JSON 解析版）**：使用能力后 LLM 用结构化 JSON 评价成功/失败 + 反思 + 是否需要重写能力卡，可真正修订 `description` / `how_to_use`
- **真实 LLM 工具调用接通 tool_learning**：所有非个人能力的工具调用也会进 `_record_tool_usage`，让"工具自学习"对 Sylanne / 各类 MCP 工具都起作用
- **WebUI 编辑器 30s 后台轮询同步**：编辑器保存后不需要等下条消息，最多 30s 自动写入 self_notes.md
- **`code_execution_safety_level` 三档真正分化**：strict（无 import）/ balanced（json/re/math/datetime）/ permissive（再加 hashlib/itertools/collections/string/statistics）
- **`capability_system_enabled` 真生效**：dispatcher 注册、能力创建、能力注入三处全部门控
- **`dynamic_tool_registration_enabled` + `default_register_as_independent_tool` 真生效**：能力合成 prompt 现在让 LLM 输出 `should_register_as_tool` 字段，置信度 ≥0.65 + 标记 true 才会真注册成独立 LLM 工具
- 新指令 `/anima_capabilities`、`/anima_autonomy`、`/anima_export_capabilities`、`/anima_core`

### 清理
- 删除过时的 `autonomous_web_tools` 配置（v0.3.6 起就没用了）
- 删除 README 中"需配置 fetch/search MCP"过时描述
- 删除仓库中遗留的 schema 历史备份与调试脚本

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
