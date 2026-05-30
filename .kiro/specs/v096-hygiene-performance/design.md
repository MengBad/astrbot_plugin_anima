# 设计文档

## Overview

v0.9.6 是一次纯卫生 + 性能的局部修复，不引入新子系统。改动分布在 `relations.py`（跨关系传播触发）、`feedback.py`（反馈阈值 + embedding 自检）、`scars.py`（压抑去重）、`rumination.py`（矛盾去重+上限）、`capabilities.py`（工具记录上限）、`main.py`（initialize 调 embedding 自检）、`_conf_schema.json`（新配置项）。

核心原则：复用既有工具（`capability_dedup.text_similarity`、各处 `[-N:]` 裁剪）、不调 LLM、失败旁路、所有阈值可配且有合理默认。

## Architecture

| 需求 | 文件 | 改动 |
| --- | --- | --- |
| R1 跨关系触发收紧 | `relations.py` | 阈值/门槛改可配 |
| R2 反馈阈值收紧 | `feedback.py` | 三段判定改可配 |
| R3 压抑去重 | `scars.py` | `_add_suppressed_topic` 加相似度比对 |
| R4 矛盾去重+上限 | `rumination.py` | 写入前去重 + `[-50:]` |
| R5 工具记录上限 | `capabilities.py` | `_record_tool_usage` 后 `[-200:]` |
| R6 embedding 自检 | `feedback.py` + `main.py` | 新增 `_check_embedding_availability` + initialize 调用 |
| 配置项 | `_conf_schema.json` | 6 个新项 |

## Components and Interfaces

### R1: 跨关系传播触发收紧（relations.py）

`_update_user_low_emotion_streak`：

```python
def _update_user_low_emotion_streak(self, uid, score):
    low_threshold = float(self.config.get("cross_relation_low_emotion_threshold", 0.2))
    streak_threshold = int(self.config.get("cross_relation_streak_threshold", 5))
    ...
    def _update(state):
        streaks = state.get("user_low_emotion_streaks", {})
        if score < low_threshold:          # 0.35 → 可配 0.2
            streaks[uid] = streaks.get(uid, 0) + 1
        else:
            streaks[uid] = 0
        ...
        if streaks.get(uid, 0) >= streak_threshold:   # 3 → 可配 5
            triggered_propagate["v"] = True
```

> 效果：日常闲聊（0.0–0.25）不再被当低情绪每轮累加；即便偶尔低于 0.2，也要连续 5 次才触发。传播效果（+0.04 微调）不变。

### R2: 反馈阈值收紧（feedback.py）

`_evaluate_feedback` 的判定段：

```python
acc_t = float(self.config.get("feedback_accepted_threshold", 0.45))
ign_t = float(self.config.get("feedback_ignored_threshold", 0.15))
if sim >= acc_t:
    return "accepted"
if sim < ign_t:
    return "ignored"
return "none"   # 中间区段改判 none（此前保守判 accepted）
```

> 把"中间区段判 accepted"改为"判 none"，避免日常对话延续被大量误判 accepted。明确否定词优先判 rejected 不变。

### R3: 压抑话题语义去重（scars.py）

`_add_suppressed_topic` 加入前比对：

```python
from ..capability_dedup import text_similarity as _ext_text_sim
def _add_suppressed_topic(self, topic, source, target_user=""):
    topics = self._read_suppressed_topics()
    threshold = float(self.config.get("dedup_text_threshold", 0.7))
    for t in topics:
        if t.get("resolved"):
            continue
        if _ext_text_sim(topic, t.get("topic", "")) >= threshold:
            return  # 已有相似未解决话题，不重复加
    topics.append({...})  # 既有逻辑
    ...
```

### R4: 矛盾去重 + 上限（rumination.py）

矛盾写入处（`_maybe_detect_contradiction`）：

```python
from ..capability_dedup import text_similarity as _ext_text_sim
contradictions = self._read_contradictions()
threshold = float(self.config.get("dedup_text_threshold", 0.7))
# 去重：与近期矛盾比对
if any(_ext_text_sim(result, c.get("description", "")) >= threshold
       for c in contradictions[-10:]):
    return  # 重复矛盾，不记录（但仍可写 self_notes？设计选择：连 self_notes 也跳过，避免噪音）
contradictions.append({...})
# 上限裁剪
cmax = int(self.config.get("contradiction_max", 50))
contradictions = contradictions[-cmax:]
self._write_contradictions(contradictions)
```

> 设计选择：去重命中时整条跳过（不写 contradictions、不写 self_notes、不触发研究），因为重复矛盾的 self_notes 注入也是噪音。

### R5: 工具记录上限（capabilities.py）

`_record_tool_usage` 中 `tl["records"].append(record)` 后：

```python
tl["records"].append(record)
rmax = int(self.config.get("tool_records_max", 200))
tl["records"] = tl["records"][-rmax:]
```

> `_summarize_tool_rules` 读 `records[-10:]` 并按 tool 过滤，裁剪只丢最旧的，不影响其行为。

### R6: embedding 自检（feedback.py + main.py）

`feedback.py` 新增：

```python
async def _check_embedding_availability(self) -> bool:
    if not self.config.get("embedding_provider_id"):
        return False
    try:
        v = await self._embed_one("健康检查")
        return bool(v) and isinstance(v, list) and len(v) > 0
    except Exception:
        return False
```

`main.py` 的 `initialize()` 末尾：

```python
try:
    if self.config.get("embedding_provider_id"):
        ok = await self._check_embedding_availability()
        if ok:
            logger.info("[Anima] embedding 可用性自检：通过")
        else:
            logger.warning("[Anima] embedding 可用性自检：失败，相似度计算将回退 Jaccard（精度下降）")
    else:
        logger.info("[Anima] 未配置 embedding_provider_id，相似度计算走本地 Jaccard")
except Exception as e:
    logger.debug(f"[Anima] embedding 自检异常（不影响运行）: {e}")
```

## Data Models

无新增数据结构。集合裁剪仅限长度。

### 配置项（_conf_schema.json 新增）

```jsonc
"cross_relation_low_emotion_threshold": { "type":"float","default":0.2,
  "hint":"⚪ Token 无。v0.9.6：跨关系传播的低情绪判定阈值。情绪评分低于此值才计入连续低情绪（此前 0.35 对日常闲聊过宽，导致每轮触发）" },
"cross_relation_streak_threshold": { "type":"int","default":5,
  "hint":"⚪ Token 无。v0.9.6：连续低情绪达此次数才触发跨关系传播（此前 3 次，过于频繁）" },
"feedback_accepted_threshold": { "type":"float","default":0.45,
  "hint":"⚪ Token 无。v0.9.6：反馈判 accepted 的相似度阈值（此前 0.30 过松，日常对话延续几乎全判 accepted）" },
"feedback_ignored_threshold": { "type":"float","default":0.15,
  "hint":"⚪ Token 无。v0.9.6：反馈判 ignored 的相似度阈值，低于此值判 ignored；与 accepted 之间判 none（中性）" },
"contradiction_max": { "type":"int","default":50,
  "hint":"⚪ Token 无。v0.9.6：矛盾记录最大保留条数（此前无上限会无限膨胀）" },
"tool_records_max": { "type":"int","default":200,
  "hint":"⚪ Token 无。v0.9.6：工具学习记录最大保留条数" },
"dedup_text_threshold": { "type":"float","default":0.7,
  "hint":"⚪ Token 无。v0.9.6：压抑话题/矛盾记录加入前的文本相似度去重阈值（字符 2-gram Jaccard）" }
```

## Correctness Properties

### Property 1: 跨关系传播触发条件
*对任意* 情绪序列，仅当存在连续 ≥ `cross_relation_streak_threshold` 次评分 `< cross_relation_low_emotion_threshold` 时才触发传播；任一次评分不低于阈值即清零计数。
**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: 反馈三段判定
*对任意* 相似度 sim 与无否定词的输入，判定为 accepted 当且仅当 `sim >= accepted_t`；ignored 当且仅当 `sim < ignored_t`；其余为 none。含否定词恒为 rejected。
**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

### Property 3: 压抑话题去重幂等
*对任意* 已存在未解决话题，加入与其相似度 ≥ 阈值的新话题不增加集合条数。
**Validates: Requirements 3.1, 3.2**

### Property 4: 矛盾去重 + 上限不变量
*对任意* 写入序列，相似矛盾不重复记录，且 contradictions 长度始终 <= contradiction_max。
**Validates: Requirements 4.1, 4.2, 4.3**

### Property 5: 工具记录上限不变量
*对任意* 追加序列，tool_records 长度始终 <= tool_records_max，且保留的是最近的记录。
**Validates: Requirements 5.1, 5.2**

## Error Handling

| 场景 | 策略 | 需求 |
| --- | --- | --- |
| text_similarity 异常 | 返回 0（视为不相似，不误去重/不漏写） | 3.3, 4.1 |
| embedding 自检异常 | 记录 debug，不阻塞 init | 6.3 |
| 配置项类型异常 | float()/int() 包 try 或用默认 | 7.3 |
| 各裁剪/状态更新异常 | 既有 try 兜底 | 7 |

## Testing Strategy

- **属性测试（Hypothesis，≥100 迭代，每属性单测试）**：覆盖 5 条 Correctness Property。
- **示例测试**：embedding 自检通过/失败/未配置；配置项存在性与默认值。
- **回归**：既有 259 测试全过。
- 测试基础设施沿用 `tests/` 现有桩 + 最小宿主约定（`_cap_host`/`_danger_host` 风格）。
