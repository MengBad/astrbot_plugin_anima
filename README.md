# Anima - 自主叙事记忆引擎

让任何 AstrBot 角色拥有自主叙事记忆、立场演化和自我认知能力的引擎。

## 定位

Anima 是 Sylanne 插件（情绪关系引擎）的附属插件，但可以独立运行。

- **Sylanne** 负责"关系走到了哪里"
- **Anima** 负责"角色知道自己是谁"

## 功能

### 情绪触发沉淀
每条 LLM 回复后，轻量评估情绪强度。超过阈值时，异步调用 LLM 以角色第一人称写一段内心独白，存入 `self_notes.md`。

### 对话前注入
每次对话前读取 `self_notes.md`，注入到对话上下文中，让角色保持自我认知的连续性。

### 向量记忆检索（可选）
使用 AstrBot 原生知识库 API 进行向量存储和检索。需要配置 Embedding Provider ID。未配置时其余功能正常运行。

### Sylanne 状态读取
尝试读取 Sylanne 的 `query_agent_state` 工具返回的状态。读取失败时正常运行，不报错。

### 演化日志
每次 `self_notes` 更新，在 `evolution_log.jsonl` 追加一条记录。

## 指令

| 指令 | 说明 |
|------|------|
| `/anima_notes` | 查看当前自我认知摘要 |
| `/anima_log [n]` | 查看最近 n 条演化记录（默认5） |
| `/anima_reset` | 重置 self_notes（保留 evolution_log） |

## 配置项

| 配置 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| enabled | bool | true | 启用 Anima 引擎 |
| emotion_threshold | float | 0.6 | 触发沉淀的情绪强度阈值（0-1） |
| seed_persona | string | "" | 初始自我描述种子 |
| sylanne_integration | bool | true | 是否尝试读取 Sylanne 状态 |
| notes_max_length | int | 5000 | self_notes 最大字符数，超出时压缩 |
| embedding_provider_id | string | "" | Embedding Provider ID，留空禁用向量记忆 |
| log_level | string | "info" | 日志级别（debug/info） |

## 向量记忆配置

向量记忆功能依赖 AstrBot 的知识库系统：

1. 在 AstrBot WebUI 的「服务提供商」页面添加一个 Embedding 类型的提供商（推荐硅基流动的 BAAI/bge-m3，免费）
2. 在 Anima 插件配置中填写该提供商的 ID
3. 插件会自动创建名为 `anima_memory` 的知识库

未配置时，情绪沉淀和自我认知功能仍然正常工作，只是不会有语义检索辅助。

## 存储路径

所有数据存在 `data/plugin_data/astrbot_plugin_anima/` 下：

```
data/plugin_data/astrbot_plugin_anima/
├── self_notes.md          叙事性自我认知，人类可读
├── persona_core.yaml      底线规则，插件只读不写
└── evolution_log.jsonl    版本历史
```

## 注意事项

- 沉淀是异步的，不会阻塞主对话流程
- 所有 LLM 调用都有超时和错误处理
- `self_notes` 超过 `notes_max_length` 时会自动调用 LLM 压缩
- 无额外 Python 依赖，完全使用 AstrBot 原生 API

## 依赖

- AstrBot >= v4.25
- 无额外 pip 依赖

## 安装

将本插件目录放入 AstrBot 的 `data/plugins/` 目录下，重启 AstrBot 即可。
