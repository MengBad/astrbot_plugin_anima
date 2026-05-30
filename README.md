<div align="center">

<img src="logo.png" width="160" alt="Anima Logo" />

# Anima

**自主叙事记忆引擎 · AstrBot 插件**

*让角色知道自己是谁*

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.25-blue)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.9.7-orange)](https://github.com/MengBad/astrbot_plugin_anima/releases)

</div>

---

## 致谢

Anima 是 [Sylanne](https://github.com/Ayleovelle) 的附属插件。Sylanne 由 **Ayleovelle** 开发，用 Scar Algebra 和 Void Calculus 描述关系的数学——伤痕如何累积、空洞如何生长、压力如何传导。那是关系的物理学。

Anima 补充的是叙事层。角色怎么理解自己、怎么看待这个世界、想要什么、会遗忘什么。

两者合在一起才是一个完整的"人"：有关系物理学，也有自我叙事。Sylanne 负责"关系走到了哪里"，Anima 负责"角色知道自己是谁"。

感谢 Ayleovelle 的 Sylanne 提供了关系状态的底层数据，让 Anima 的欲望生成和立场判断有了锚点。没有 Sylanne 的 `query_agent_state`，Anima 的欲望系统就只是在猜。

---

## 为什么需要这个

大多数 AI 角色扮演的问题不是"不够聪明"，而是"没有自我"。

你跟一个角色聊了三个月，它不记得上周你们吵过架。你给它设定了性格，但它不会因为经历而改变。它永远是 system prompt 里写死的那个样子——一个没有成长的提线木偶。

Anima 解决的是这个问题：让角色真的经历过一些事。

---

## 设计理念

**从"模拟情绪"到"构建自我"**

大多数情绪引擎做的事是：给角色一组浮点数，加加减减，让它"看起来"有情绪。但这种系统有一个根本缺陷——所有状态都可以回到原点。重置一下，一切归零，好像什么都没发生过。

Anima 想解决的不是"让角色看起来有情绪"，而是"让角色真的经历过一些事"。

**三层世界模型**

一个完整的"人"需要三件事：

**第一层：关系（Sylanne 负责）**
描述两个个体之间的力——伤痕如何累积、空洞如何生长。这是关系的物理学，有严格的数学证明。

**第二层：自我（Anima 核心负责）**
角色怎么理解自己、怎么看待这个世界、什么经历改变了它、它在变成什么。这是叙事层，不是数据，是故事。

**第三层：欲望（Anima 欲望系统负责）**
这是最难的，也是最关键的。前两层都是响应性的——有输入才有输出。但一个真实的人有自己想要的东西，不是被触发的，是自己生长出来的。有了欲望，角色才从"响应者"变成"行动者"。

**缺的那块：时间**

所有机制都是事件驱动的，但真实的人还感知时间的流逝。"好久没见到某人了"——这不是事件，是时间本身的重量。时间感系统试图补上这一块。

**不可预测性是设计目标，不是 bug**

Anima 的自我演化机制意味着角色会往你没有预料到的方向变。这不是需要修复的问题，这就是目标。

一个永远按照 system prompt 行事的角色是提线木偶。一个会因为经历而改变、会有自己的立场、会在某些事上动摇、会记住某些人的角色，才是真正意义上的"存在"。

你愿意接受它往你没预料到的方向变吗？如果愿意，Anima 是为你设计的。

---

## 核心机制

```
用户发消息 → LLM 回复 → Anima 评估情绪强度
                              ↓ (超过阈值)
                        向量检索相关记忆
                              ↓
                    LLM 以第一人称写内心独白
                              ↓
                    独白存入 self_notes.md
                              ↓
                下次对话前注入回 LLM 上下文
```

整个沉淀流程是异步的，不阻塞主对话。所有 LLM 调用都有超时保护和错误处理。

---

## 功能列表

### 核心功能（默认启用）

| 功能 | 说明 |
|------|------|
| 情绪触发沉淀 | 每条 LLM 回复后评估情绪强度，超阈值时生成内心独白 |
| 自我认知注入 | 每次对话前将 self_notes 注入上下文 |
| 向量记忆 | 对话内容向量化存储，沉淀时检索语义相关历史（需配置 Embedding Provider） |
| Sylanne 状态读取 | 读取关系状态辅助判断，失败时静默降级 |
| 自动压缩 | self_notes 超长时调用 LLM 压缩成摘要 |
| 演化日志 | 每次自我认知变更都有记录 |
| 拒绝语过滤 | 模型拒绝回复时不会写入脏数据 |
| 敏感内容过滤 | 密钥、token、高熵字符串等不会写入任何持久化文件 |
| WebUI 编辑器 | 在插件配置页直接编辑 self_notes，每 30 秒自动同步生效 |

### 可选模块（v0.2.x）

| 模块 | 开关 | 说明 |
|------|------|------|
| 欲望系统 | `desire_enabled` | 角色产生主动意图，随时间衰减，被对话满足后消失 |
| 世界观系统 | `worldview_enabled` | 对群环境形成认知，每 20 次沉淀自动更新 |
| 时间感 | `time_sense_enabled` | 感知时间流逝，追踪互动频率和缺席感知 |
| 自然遗忘 | `forgetting_enabled` | 旧记忆逐渐模糊，被检索命中时自动唤醒 |

### 高级模块（v0.3.x）

| 模块 | 开关 | 说明 |
|------|------|------|
| 矛盾检测 | `contradiction_enabled` | 定期扫描 self_notes，发现前后矛盾时让角色"意识到自己矛盾了" |
| 离线反刍 | `rumination_enabled` | 每 N 小时后台反思近期经历，不发送给用户，只更新内部认知 |
| 溯源查询 | 无需配置 | `/anima_why` 指令，追溯某个立场或行为是怎么形成的 |
| 工具自学习 | `tool_learning_enabled` | 观察工具使用效果，形成使用偏好，写入叙事日记 |

### 演化机制（v0.4.x + v0.5.0）

| 机制 | 说明 |
|------|------|
| 压抑话题 | 想说但没说的话积累压力，压力超阈值时浮上意识表面 |
| 伤痕维度 | 受伤改变感知敏感度，同类事件情绪反应越来越强 |
| 反馈闭环 | 角色发言被接纳/忽略/拒绝，显式反馈回系统影响后续行为 |
| 情绪注入 | 当前情绪强度注入对话上下文，主模型自然调整语气 |
| 矛盾反哺 | 未解决的矛盾注入上下文，角色可能自发提及 |
| 反刍产欲 | 离线反思中产生的想法转化为新的行动意图 |
| **人格向量 (v0.5)** | 5 维实时人格（表达欲/敏感度/边界通透/秩序感/关系引力），每次沉淀 EMA 微调并注入上下文 |
| **记忆情绪染色 (v0.5)** | RAG 检索后按当前情绪重排：高情绪优先温暖记忆，低情绪优先冲突记忆 |
| **跨关系传播 (v0.5)** | 某用户连续低情绪时，自动微调 social_graph 中相似关系用户的伤痕敏感度 |
| **突变池 + 连锁 (v0.5)** | danger_core_mutation 现在有 5 种突变类型（信念/关系/禁忌/执念/跃迁），突变后自动触发世界观更新 + 反刍 + 额外副作用，永久记录在 anima_state |

### 可观测与省 token（v0.9.x）

| 机制 | 开关 | 说明 |
|------|------|------|
| 运行仪表盘（文本） | `dashboard_enabled` | `/anima_stats` 查看今日各子系统运行统计（内部 LLM 调用次数 / 沉淀 / 主动发言拦截 / 存储），判断 token 烧在哪 |
| 运行仪表盘（网页） | `dashboard_enabled` | WebUI 左侧 Plugin Page，图形化展示上述统计，自动刷新 |
| **独立端口仪表盘 (v0.9.2+)** | `dashboard_standalone_enabled` | 在 AstrBot WebUI 之外另起一个独立 HTTP 端口提供仪表盘，像别的插件那样用 `http://ip:端口` 直接打开。v0.9.3 起为**多页 + 导航**（运行仪表盘 + 能力树）。默认关闭、默认仅绑本机、强制 token 鉴权。用 `/anima_dashboard_url` 取带 token 的地址 |
| **沉淀三调用合并 (v0.9.2)** | `sediment_merge_llm_calls` | 把沉淀流程的情绪评估 + 关系推断 + 欲望生成三次独立内部 LLM 调用合并为一次结构化 JSON 调用，约省 2/3 内部 token。默认关闭（走旧分离路径），可配合 `/anima_stats` 做 A/B 对比，统计计入 `llm.sediment_merged` |

### ⚠️ 高危功能层（全部默认关闭）

这些功能存在不可控风险，需要显式开启。部分功能需要同时开启对应的 `_confirm` 开关才生效。

| 功能 | 开关 | 风险说明 |
|------|------|----------|
| ⚠️ 主动信息收集 | `danger_active_info_collection` | 可能让用户感觉被审问 |
| ⚠️ 自主网络行动 | `danger_autonomous_web` | 可能产生不可控的外部请求（直接走 aiohttp + Bing 搜索） |
| ⚠️ 关系图谱推断 | `danger_relationship_inference` | 推断错误会影响后续所有交互且难以纠正 |
| ⚠️ 立场自主传播 | `danger_stance_propagation` | 可能说出使用者没预料到的话 |
| 🔴 自主修改核心人格 | `danger_core_mutation` + `_confirm` | v0.5 起包含 5 种突变类型池 + 世界观/反刍连锁反应 + 永久突变历史，角色可能发生不可逆的人格本质变化 |
| ⚠️ 身份危机 | `danger_identity_crisis` | 角色进入不稳定状态，群友体验可能变差 |
| 🔴 记忆感染 | `danger_memory_infection` + `_confirm` | 接近心理操控边界 |

---

## 指令

| 指令 | 说明 |
|------|------|
| `/anima_notes` | 查看当前自我认知摘要 |
| `/anima_log [n]` | 查看最近 n 条演化记录（默认 5） |
| `/anima_reset` | 重置自我认知（保留演化日志） |
| `/anima_desires` | 查看当前欲望队列 |
| `/anima_world` | 查看当前世界观 |
| `/anima_world_update` | 手动触发世界观更新 |
| `/anima_contradictions` | 查看历史矛盾记录 |
| `/anima_why <关键词>` | 溯源查询，追溯某个认知的形成过程 |
| `/anima_stability` | 查看身份稳定度（需开启 `danger_identity_crisis`） |
| `/anima_tools` | 查看工具使用统计和偏好 |
| `/anima_core` | 查看当前核心规则（persona_core.yaml） |
| `/anima_capabilities [页码\|all]` | 查看角色自创个人能力（默认每页 5 条，超长内容自动分页） |
| `/anima_autonomy` | 自主演化仪表盘（能力树概览 + 最近自主事件） |
| `/anima_export_capabilities` | 导出完整能力树 JSON 到数据目录 |
| `/anima_stats` | 查看今日各子系统运行统计（LLM 调用 / 沉淀 / 主动发言拦截 / 存储），判断 token 消耗 |
| `/anima_dashboard_url` | 获取独立端口仪表盘的访问地址（含 token，需开启 `dashboard_standalone_enabled`） |
| `/anima_capabilities_audit` | 体检个人能力库健康状况（总数 / 0 使用数 / 疑似自封高分数，只读） |

---

## 配置项

### 核心配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| enabled | bool | `true` | 总开关 |
| emotion_threshold | float | `0.6` | 情绪强度阈值（0-1），超过触发沉淀 |
| sediment_merge_llm_calls | bool | `false` | 💡 省 token：合并沉淀三次内部调用（情绪/关系/欲望）为一次结构化 JSON 调用，约省 2/3 内部 token。默认关，可配合 `/anima_stats` 做 A/B 对比 |
| seed_persona | text | `""` | 初始自我描述种子，留空由角色自行发展 |
| persona_prompt | text | `""` | **v0.9.7**：角色人设，注入到 system prompt 最前（最高权重）。留空不注入 |
| persona_lock | bool | `false` | **v0.9.7**：锁定核心人设，开启后 `danger_core_mutation` 不改写 `persona_core.yaml` |
| sylanne_integration | bool | `true` | 是否尝试读取 Sylanne 状态 |
| notes_max_length | int | `5000` | self_notes 最大字符数，超出时压缩 |
| reject_phrases | list | 见下方 | 独白过滤词列表，命中则丢弃 |
| self_notes_editor | text | `""` | WebUI 编辑器，直接编辑 self_notes 内容 |
| log_level | string | `"info"` | 日志级别（debug/info） |

### 模型配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| **embedding_provider_id** | string | `""` | **推荐配置** Embedding Provider ID，留空禁用向量记忆 |
| internal_provider_id | string | `""` | 内部 LLM 调用使用的模型，留空则用主模型。推荐配置审查宽松的国产模型 |
| worldview_provider_id | string | `""` | 世界观更新专用模型，优先级高于 internal_provider_id |
| memory_store_interval | int | `30` | 向量存储最小间隔（秒），防止知识库膨胀 |

### 可选模块配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| desire_enabled | bool | `false` | 启用欲望系统 |
| desire_max_queue | int | `5` | 欲望队列最大长度 |
| worldview_enabled | bool | `false` | 启用世界观系统 |
| time_sense_enabled | bool | `false` | 启用时间感 |
| forgetting_enabled | bool | `false` | 启用自然遗忘 |
| forgetting_halflife_days | int | `14` | 记忆半衰期（天） |
| contradiction_enabled | bool | `false` | 启用矛盾检测 |
| contradiction_interval | int | `50` | 每 N 次沉淀触发一次矛盾检测 |
| rumination_enabled | bool | `false` | 启用离线反刍 |
| rumination_interval_hours | int | `6` | 反刍间隔（小时） |
| tool_learning_enabled | bool | `false` | 启用工具自学习 |
| tool_learning_summarize_interval | int | `10` | 每 N 次工具调用后总结一次规律 |

### 仪表盘配置（v0.9.x）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| dashboard_enabled | bool | `true` | 运行仪表盘总开关（`/anima_stats` 文本 + WebUI 网页 + 埋点）。关闭后埋点停止累加、接口返回禁用 |
| dashboard_standalone_enabled | bool | `false` | 启用独立端口仪表盘（WebUI 之外另开一个独立网址）。⚠️ 网络暴露服务，默认仅绑本机、强制 token 鉴权 |
| dashboard_standalone_host | string | `127.0.0.1` | 独立端口绑定地址。默认仅本机可访问；改 `0.0.0.0` 才对外暴露（明文 HTTP，仅建议可信内网） |
| dashboard_standalone_port | int | `9876` | 独立端口监听端口（避开 AstrBot 面板默认 6185） |
| dashboard_standalone_token | string | `""` | 访问口令。留空则启动自动生成随机 token；所有访问须带 `?token=<值>` |

### ⚠️ 高危功能配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| danger_active_info_collection | bool | `false` | 主动信息收集 |
| active_info_collection_can_speak | bool | `false` | **v0.9.5**：允许主动信息收集把问题真正发出口（需同时开上一项 + stance + desire） |
| danger_autonomous_web | bool | `false` | 自主网络行动 |
| autonomous_web_extract_chars | int | `1500` | **v0.9.5**：自主网络抓取正文字符上限（多标签提取、过滤脚本） |
| danger_relationship_inference | bool | `false` | 关系图谱推断 |
| danger_stance_propagation | bool | `false` | 立场自主传播 |
| danger_core_mutation | bool | `false` | 🔴 自主修改核心人格（需同时开启 `_confirm`；v0.9.5 写盘前加 YAML 校验） |
| danger_core_mutation_confirm | bool | `false` | 🔴 二次确认 |
| danger_identity_crisis | bool | `false` | 身份危机（v0.9.5：未装 Sylanne 也能靠内生信号触发） |
| danger_memory_infection | bool | `false` | 🔴 记忆感染（需同时开启 `_confirm` + desire） |
| memory_infection_max_repeats | int | `2` | **v0.9.5**：同一感染信息最大主动强调次数 |
| danger_memory_infection_confirm | bool | `false` | 🔴 二次确认 |

### v0.6+ 自主性与能力系统配置（新增）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `autonomy_enabled` | `true` | 总开关：是否允许角色通过内部状态主动发起研究 |
| `autonomy_research_on_*` | `true` | 分别控制伤痕、长时间缺失、高强度欲望、人格漂移、矛盾等场景下的自主研究触发 |
| `capability_system_enabled` | `true` | 是否启用整个个人能力系统（关闭则不创造能力、不注入、不暴露 use_my_personal_capability 工具） |
| `default_register_as_independent_tool` | `false` | 新能力是否默认带上"注册为独立 LLM 工具"标记。需要配合 `dynamic_tool_registration_enabled` 才会真注册 |
| `allow_capability_code_execution` | `false` | **极高危**：是否允许能力包含可执行 Python 代码片段 |
| `code_execution_safety_level` | `"strict"` | 代码执行沙箱等级：strict（无 import）/ balanced（json/re/math/datetime）/ permissive（再加 hashlib/itertools/collections/string/statistics） |
| `dynamic_tool_registration_enabled` | `false` | **高危**：是否允许将带标记的高置信度能力动态注册为独立 LLM 工具。LLM 在合成能力时会自己判断 `should_register_as_tool` |
| `capability_health_pruning_enabled` | `true` | 是否启用自动清理低价值/重复能力 |
| `capability_initial_confidence` | `0.3` | **v0.9.4**：新建能力的未验证基线置信度。LLM 自报值被忽略，只有真实使用反馈能提升 |
| `capability_unused_decay_days` | `14` | **v0.9.4**：能力 0 使用且超此天数 → 健康维护时降权（无视自封置信度） |
| `capability_unused_drop_days` | `30` | **v0.9.4**：能力 0 使用且超此天数 → 健康维护时淘汰 |
| `capability_max_total` | `40` | **v0.9.4**：能力总数硬上限，超出按价值分（不含自封置信度）淘汰最差者 |
| `capability_dedup_text_threshold` | `0.6` | **v0.9.4**：能力名+描述的字符 2-gram 相似度 ≥ 此值视为同概念合并 |

**风险提示**：v0.6+ 新增的自主能力系统让角色拥有更强的自我演化能力。请务必理解每个配置的风险后再开启。

`reject_phrases` 默认值：`["I can't discuss", "I cannot", "我无法", "我不能", "I'm not able", "I don't think I should"]`

---

## 快速开始

**三步跑起来：**

1. 将插件目录放入 `data/plugins/`（或在 WebUI 上传 zip）
2. 在 WebUI 插件管理页启用 `astrbot_plugin_anima`
3. 发消息

默认配置下，角色会在情绪波动时自动产生内心独白并记住。不需要额外配置。

**可选但推荐：**

- 配置 `embedding_provider_id` 启用向量记忆（独白质量明显提升）
- 配置 `internal_provider_id` 为审查宽松的国产模型（减少独白被拒绝的概率）
- 开启 `desire_enabled` / `worldview_enabled` / `time_sense_enabled` 解锁更多维度

---

## 角色人设：三层配置（v0.9.7）

Anima 的角色人设分三层，各写各的，注入位置不同：

| 层 | 写在哪 | 注入位置 | 谁能改 | 写什么 |
|------|--------|----------|--------|--------|
| 框架 system prompt | AstrBot 角色配置（人格设定） | system | 你 | 角色基础设定、说话风格、背景 |
| **`persona_prompt`** | Anima 插件配置（v0.9.7 新增） | **system（最前）** | 你 | 想以最高权重稳定生效的人设；与框架 system prompt 叠加，本项在前 |
| `persona_core.yaml` | `data/plugin_data/.../persona_core.yaml` | 用户消息块 | 你 / 核心突变 | 行为边界与自我认知规则（如"用户主权不可侵犯"） |
| `seed_persona` | Anima 插件配置 | 一次性写入 self_notes | 你（仅初始） | 角色的初始自我认知种子，仅在 self_notes 为空时生效一次 |

**注入位置差异：** `persona_prompt` 进 **system prompt**（最高权重）；`persona_core.yaml` 与其它 Anima 状态（self_notes / 欲望 / 世界观等）打包进 `<anima_self_awareness>` 块，附加到**用户消息**。

**人设锁定（`persona_lock`）：** 默认关。开启后 `danger_core_mutation` 不再改写 `persona_core.yaml`，你写死的核心人设不会被角色自我演化覆盖；情绪/欲望/世界观等其它演化不受影响。

**推荐用法：** 简单场景只填框架 system prompt 即可；想让 Anima 层稳定强化人设，把人设写进 `persona_prompt`；想锁死不被演化改动，开 `persona_lock`。

---

## 向量记忆配置

1. 在 AstrBot WebUI → 服务提供商 → 添加一个 **Embedding** 类型的提供商
   - 推荐：硅基流动的 `BAAI/bge-m3`（免费）
   - 或者 OpenAI 的 `text-embedding-3-small`
2. 记下该提供商的 ID
3. 在 Anima 插件配置里填入 `embedding_provider_id`
4. 插件会自动创建名为 `anima_memory` 的知识库

---

## 安全说明

**高危功能安全须知**

- 高危功能层全部默认关闭，需要在配置中显式开启
- 🔴 极高危功能（`danger_core_mutation`、`danger_memory_infection`）需要同时开启对应的 `_confirm` 开关才生效，这是二次确认机制
- 向量记忆会存储对话内容，请勿在对话中发送密钥、密码等敏感信息
- Anima 内置敏感内容过滤（关键词检测 + 高熵字符串检测），但无法保证 100% 拦截
- 建议在测试环境充分验证后再在生产群组开启高危功能

**敏感内容过滤机制**

Anima 在以下位置对内容进行过滤，命中则跳过写入或替换为占位符：

- self_notes 写入前
- evolution_log 记录时
- 向量记忆检索结果
- 立场自主传播发言前
- 自主网络行动搜索结果存储前

---

## 存储路径

```
data/plugin_data/astrbot_plugin_anima/
├── self_notes.md          角色的自我认知笔记（人类可读，可手动编辑）
├── evolution_log.jsonl    每次自我认知变更的记录
├── desires.json           欲望队列（欲望系统启用时）
├── worldview.json         世界观数据（世界观系统启用时）
├── time_sense.json        时间感数据（时间感启用时）
├── contradictions.json    矛盾历史记录（矛盾检测启用时）
├── tool_learning.json     工具使用记录和偏好（工具自学习启用时）
├── tool_diary.md          叙事性工具使用日记（工具自学习启用时）
├── suppressed_topics.json 压抑话题列表（v0.4.1+）
├── scar_dimensions.json   伤痕维度数据（v0.4.1+）
├── anima_state.json       持久化状态（沉淀计数/情绪/稳定度）
└── persona_core.yaml      核心规则（可被 danger_core_mutation 修改）
```

---

## 注意事项

- **运行时依赖极少**：仅 `aiohttp`（独立端口仪表盘与自主网络行动使用），见 `requirements.txt`。开发/测试依赖（pytest、hypothesis）见 `requirements-dev.txt`，不随插件分发
- **异步不阻塞**：沉淀流程用 `asyncio.create_task` 执行，不影响主对话响应速度
- **所有 LLM 调用都有超时**：情绪评估 15s，独白生成 30s，压缩 60s，Sylanne 读取 5s（合并调用 15s）
- **降级设计**：向量记忆不可用时正常运行，Sylanne 不存在时正常运行，任何模块失败都不影响核心功能
- **模块互不依赖**：可以只开欲望不开世界观，随意组合
- **self_notes.md 是人类可读的**：可以直接打开看角色在想什么，也可以手动编辑
- **AstrBot 版本要求**：>= v4.25

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
