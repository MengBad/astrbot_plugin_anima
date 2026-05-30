# Implementation Plan: v0.9.9 人物认知全局化（群环境仍按群隔离）

## Overview

把 social_graph + relationships 从 per-umo worldview 抽到全局 social_graph.json，群环境保持按群隔离。核心是把分流封装进 `_read_worldview`（返回合并视图）和 `_write_worldview`（内部分流），让绝大多数调用点零改动。

实现语言 Python，沿用 `anima/mixins/` 与 `tests/` 约定。属性测试用 Hypothesis，每条 Property 单测试、≥100 迭代。

## Tasks

- [x] 1. 全局 Social_Store 基础设施
  - [x] 1.1 main.py `__init__` 加 `self.social_graph_path`；worldview.py 加 `_read_social_store`/`_write_social_store`/`_cap_dict`
    - default 结构 `{"social_graph":{}, "relationships":{}}`
    - _Requirements: 1.1, 1.2_
  - [x] 1.2 `_conf_schema.json` 加 `social_graph_max`(int,100)
    - _Requirements: 1.5_

- [x] 2. 合并视图 + 写入分流（核心）
  - [x] 2.1 worldview.py `_read_worldview(umo)` 返回合并视图
    - 读会话群环境（过滤掉残留 social_graph/relationships）+ 全局 store，合并返回
    - _Requirements: 2.3, 5.3_
  - [x] 2.2 worldview.py `_write_worldview(data, umo)` 内部分流
    - pop 出 social_graph/relationships 写全局 store（各自上限 social_graph_max/30）；其余写会话文件
    - _Requirements: 1.4, 1.5, 2.1, 2.2, 3.1_
  - [x]* 2.3 Property test: 跨群统一 + 群环境隔离 + 写入分流
    - 新建 `tests/test_v099_prop134_split.py`，**Property 1 + 2 + 3 + 4**，**Validates: 1.3,1.4,1.5,2.1,2.2,2.3,3.1,5.3**

- [x] 3. 关系写入全局
  - [x] 3.1 merged_eval.py `_apply_relationships_from_map` 改写全局 store
    - 直接读改写 social_graph.json 的 relationships（保留 _is_rejected + 30 上限）；umo 参数保留不影响存储
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 4. 世界观更新分流（验证零改动/微调）
  - [x] 4.1 worldview.py `_maybe_update_worldview` 确认走合并视图 + 分流写
    - full_graph 来自合并视图（=全局）；写回走改造后 _write_worldview 自动分流；日志措辞按需微调
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 5. 存量迁移
  - [x] 5.1 worldview.py 加 `_migrate_social_graph_v099`，main.py initialize 调用
    - 从旧全局 worldview.json + 各 sessions/*/worldview.json 收集 social_graph/relationships 并入全局 store；写 migrated_v099 标记；幂等；不删旧数据；冲突后写覆盖
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [x]* 5.2 Property test: 迁移幂等
    - 新建 `tests/test_v099_prop5_migrate.py`，**Property 5**，**Validates: 6.1, 6.2**

- [x] 6. Checkpoint - 隔离粒度测试
  - Ensure all tests pass（含既有 298；同步受 _write_worldview 行为变化影响的测试 host），ask the user if questions arise.

- [x] 7. 版本与文档
  - [x] 7.1 版本号 bump 到 0.9.9（metadata.yaml + main.py @register）
  - [x] 7.2 CHANGELOG + README 更新（人物认知全局 vs 群环境按群 + 目录结构）

- [x] 8. Final checkpoint - 全量回归
  - Ensure all tests pass，ask the user if questions arise.

## Notes

- `*` 为属性/示例测试，强烈建议执行。
- 核心红利：分流封装进 `_read_worldview`/`_write_worldview`，调用点零改动。但既有测试 host 自定义了 `_read_worldview`/`_write_worldview`（_merged_eval_host / test_v092_legacy_path），它们不经分流逻辑，需确认相关断言仍成立或同步调整。
- 迁移不删旧数据；合并视图以全局人物认知为准、过滤会话内残留。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1"] },
    { "id": 2, "tasks": ["2.3", "4.1", "5.1"] },
    { "id": 3, "tasks": ["5.2", "7.1", "7.2"] }
  ]
}
```
