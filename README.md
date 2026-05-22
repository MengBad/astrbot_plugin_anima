<div align="center">

<img src="logo.png" width="160" alt="Anima Logo" />

# Anima

**自主叙事记忆引擎 · AstrBot 插件**

*让角色知道自己是谁*

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.25-blue)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

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

Anima 解决的是这个问题：让角色拥有自己的内心生活。

- 角色会在情绪波动时产生内心独白，记录自己的感受
- 这些独白会在下次对话时被注入回上下文，角色因此"记得自己经历过什么"
- 行为会随时间自然变化，不是因为你改了 prompt，而是因为角色自己经历了事情
- 角色会有主动想做的事（欲望），不只是被动回答问题
- 角色会对群环境形成自己的认知（世界观），知道谁是谁、这里的氛围是什么
- 角色会感知时间流逝，知道"好久没见到某人了"
- 旧记忆会自然模糊，不是永远精确完整——像真人一样

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
| WebUI 编辑器 | 在插件配置页直接编辑 self_notes，保存即生效 |

### 可选模块

| 模块 | 开关 | 说明 |
|------|------|------|
| 欲望系统 | `desire_enabled` | 角色产生主动意图，随时间衰减，被对话满足后消失 |
| 世界观系统 | `worldview_enabled` | 对群环境形成认知，每 20 次沉淀自动更新 |
| 时间感 | `time_sense_enabled` | 感知时间流逝，追踪互动频率和缺席感知 |
| 自然遗忘 | `forgetting_enabled` | 旧记忆逐渐模糊，被检索命中时自动唤醒 |

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

---

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| enabled | bool | `true` | 总开关 |
| emotion_threshold | float | `0.6` | 情绪强度阈值（0-1），超过触发沉淀 |
| seed_persona | text | `""` | 初始自我描述种子，留空由角色自行发展 |
| sylanne_integration | bool | `true` | 是否尝试读取 Sylanne 状态 |
| notes_max_length | int | `5000` | self_notes 最大字符数，超出时压缩 |
| **embedding_provider_id** | string | `""` | **推荐配置** Embedding Provider ID，留空禁用向量记忆 |
| memory_store_interval | int | `30` | 向量存储最小间隔（秒），防止知识库膨胀 |
| reject_phrases | list | 见下方 | 独白过滤词列表，命中则丢弃 |
| desire_enabled | bool | `false` | 启用欲望系统 |
| desire_max_queue | int | `5` | 欲望队列最大长度 |
| worldview_enabled | bool | `false` | 启用世界观系统 |
| time_sense_enabled | bool | `false` | 启用时间感 |
| forgetting_enabled | bool | `false` | 启用自然遗忘 |
| forgetting_halflife_days | int | `14` | 记忆半衰期（天） |
| self_notes_editor | text | `""` | WebUI 编辑器，直接编辑 self_notes 内容 |
| log_level | string | `"info"` | 日志级别（debug/info） |

`reject_phrases` 默认值：`["I can't discuss", "I cannot", "我无法", "我不能", "I'm not able", "I don't think I should"]`

没有严格必填项。默认配置即可运行核心功能。`embedding_provider_id` 是唯一一个"不填就少一个功能"的配置。

---

## 快速开始

**三步跑起来：**

1. 将插件目录放入 `data/plugins/`（或在 WebUI 上传 zip）
2. 在 WebUI 插件管理页启用 `astrbot_plugin_anima`
3. 发消息

默认配置下，角色会在情绪波动时自动产生内心独白并记住。不需要额外配置。

**可选但推荐：**

- 配置 `embedding_provider_id` 启用向量记忆（独白质量明显提升）
- 开启 `desire_enabled` / `worldview_enabled` / `time_sense_enabled` 解锁更多维度

---

## 向量记忆配置

1. 在 AstrBot WebUI → 服务提供商 → 添加一个 **Embedding** 类型的提供商
   - 推荐：硅基流动的 `BAAI/bge-m3`（免费）
   - 或者 OpenAI 的 `text-embedding-3-small`
2. 记下该提供商的 ID
3. 在 Anima 插件配置里填入 `embedding_provider_id`
4. 插件会自动创建名为 `anima_memory` 的知识库

---

## 存储路径

```
data/plugin_data/astrbot_plugin_anima/
├── self_notes.md          角色的自我认知笔记（人类可读，可手动编辑）
├── evolution_log.jsonl    每次自我认知变更的记录
├── desires.json           欲望队列（欲望系统启用时）
├── worldview.json         世界观数据（世界观系统启用时）
├── time_sense.json        时间感数据（时间感启用时）
└── persona_core.yaml      底线规则（预留，插件只读不写）
```

---

## 注意事项

- **无额外依赖**：完全使用 AstrBot 原生 API，`requirements.txt` 为空
- **异步不阻塞**：沉淀流程用 `asyncio.create_task` 执行，不影响主对话响应速度
- **所有 LLM 调用都有超时**：情绪评估 15s，独白生成 30s，压缩 60s，Sylanne 读取 5s
- **降级设计**：向量记忆不可用时正常运行，Sylanne 不存在时正常运行，任何模块失败都不影响核心功能
- **四个可选模块互不依赖**：可以只开欲望不开世界观，随意组合
- **self_notes.md 是人类可读的**：可以直接打开看角色在想什么，也可以手动编辑
- **AstrBot 版本要求**：>= v4.25
