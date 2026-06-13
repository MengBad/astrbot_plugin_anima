# Release Notes - v1.3.0

## 概要

v1.3.0 是 `astrbot_plugin_anima` 的「完全体」发布版本。
本版本将版本号统一到 v1.3.0，更新全部发布文档，确认 409 个测试全绿通过。
核心叙事引擎、可观测性面板和双引擎架构保持稳定，无功能性变更。

## 核心亮点

- **版本号统一**：将 main.py、metadata.yaml、README.md 的版本号统一到 v1.3.0。
- **文档同步**：更新 RELEASE_NOTES、MIGRATION_GUIDE、KNOWN_ISSUES、TEST_REPORT 到 v1.3.0。
- **测试验证**：确认 409 个测试全部通过，覆盖核心稳定性、可观测性、安全脱敏、能力系统等。

## 兼容性说明

本次升级不需要任何数据迁移。
所有既有持久化文件均保持完全兼容：
- `anima_state.json`
- `self_notes.md`
- `desires.json`
- `persona_core.yaml`
- Sylanne `.alpha.json` 会话缓存
- AstrBot 数据库 KV 状态

## 发版建议

- 建议 tag：`v1.3.0`
- 建议发布类型：次要版本（Minor Release）
- 发版理由：版本号统一与文档同步，确认完全体状态，强烈推荐所有用户升级。
