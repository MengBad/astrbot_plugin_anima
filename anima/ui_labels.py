"""Anima 面向用户的文案：指令帮助、配置项友好名、统计 metric 中文标签。"""

from __future__ import annotations

from typing import Optional

# ── 统计 metric 中文标签（仪表盘 + /anima_stats 共用）────────────────────────

# llm.* 与 stance.blocked.* 的 short name 可能重复，按前缀分表
_LLM_LABELS: dict[str, str] = {
    "emotion": "情绪评分",
    "monologue": "内心独白生成",
    "sediment_merged": "沉淀合并调用",
    "relation": "关系图谱推断",
    "worldview": "世界观更新",
    "stance": "主动发言生成",
    "info_collection": "主动信息收集",
    "mutation": "核心人格突变",
    "memory_infection": "记忆感染",
    "research_synthesis": "自主研究合成",
    "rumination": "离线反刍",
    "contradiction": "矛盾检测",
}

_BLOCKED_LABELS: dict[str, str] = {
    "monologue": "内心独白泄漏拦截",
    "irrelevant": "话题不相关拦截",
    "dedup": "重复发言拦截",
    "low_intensity": "强度不足拦截",
    "stale": "欲望过期拦截",
    "sensitive": "敏感内容拦截",
    "rejected": "拒答内容拦截",
}

_CAPABILITY_PREFIX_LABELS: dict[str, str] = {
    "capability.promoted": "能力晋升注册",
    "capability.match.hint_injected": "能力定向提示注入",
    "capability.call.attempt": "能力调用尝试",
    "capability.call.resolved": "能力调用命中",
    "capability.call.unresolved": "能力调用未找到",
}


def label_stat_key(full_key: str) -> str:
    """把 stats 计数 key（如 llm.emotion、stance.blocked.monologue）转为中文标签。"""
    if full_key in _CAPABILITY_PREFIX_LABELS:
        return _CAPABILITY_PREFIX_LABELS[full_key]
    if full_key.startswith("llm."):
        short = full_key[len("llm.") :]
        return _LLM_LABELS.get(short, short)
    if full_key.startswith("stance.blocked."):
        short = full_key[len("stance.blocked.") :]
        return _BLOCKED_LABELS.get(short, short)
    return full_key


# ── 配置项 → 插件配置页友好名 ───────────────────────────────────────────────

CONFIG_FRIENDLY: dict[str, str] = {
    "enabled": "插件总开关",
    "dashboard_enabled": "运行仪表盘",
    "dashboard_standalone_enabled": "独立端口仪表盘",
    "dashboard_standalone_host": "独立端口绑定地址",
    "dashboard_standalone_port": "独立端口端口号",
    "dashboard_standalone_token": "独立端口访问口令",
    "dashboard_history_days": "历史趋势保留天数",
    "desire_enabled": "欲望系统",
    "worldview_enabled": "世界观系统",
    "contradiction_enabled": "矛盾检测",
    "tool_learning_enabled": "工具自学习",
    "danger_identity_crisis": "身份危机模块",
    "capability_system_enabled": "个人能力系统",
    "capability_unused_decay_days": "能力未使用降权天数",
    "capability_unused_drop_days": "能力未使用淘汰天数",
}


def config_label(key: str) -> str:
    return CONFIG_FRIENDLY.get(key, f"插件配置 → {key}")


# ── /anima_help 指令目录 ─────────────────────────────────────────────────────

HelpEntry = tuple[str, str, Optional[str]]  # command, summary, prerequisite

HELP_SECTIONS: list[tuple[str, list[HelpEntry]]] = [
    (
        "日常查看",
        [
            ("/anima_notes", "查看当前自我认知摘要", None),
            ("/anima_log [n]", "最近 n 条演化记录（默认 5）", None),
            ("/anima_desires", "查看当前会话可见的欲望队列", "需开启「欲望系统」"),
            ("/anima_world", "查看当前世界观（群环境认知）", "需开启「世界观系统」"),
            ("/anima_contradictions", "查看历史矛盾记录", "需开启「矛盾检测」"),
            ("/anima_why <关键词>", "溯源：某条认知是如何形成的", None),
            ("/anima_core", "查看核心规则 persona_core.yaml", None),
        ],
    ),
    (
        "运维 / 成本",
        [
            ("/anima_stats", "今日各子系统运行统计 + 近 7 天 LLM 趋势", "需开启「运行仪表盘」"),
            ("/anima_dashboard_url", "获取独立端口仪表盘地址（含访问口令）", "需开启「独立端口仪表盘」"),
            ("/anima_scan_rejects", "扫描知识库拒答/注入污染规模（只读）", "需启用向量记忆知识库"),
            ("/anima_tools", "工具使用统计与自学习规律", "需开启「工具自学习」"),
        ],
    ),
    (
        "能力系统",
        [
            (
                "/anima_autonomy",
                "自主演化概览：能力 Top5 + 最近自主事件",
                "需开启「个人能力系统」；偏速览，详情见 capabilities",
            ),
            (
                "/anima_capabilities [页|all]",
                "个人能力详情列表（默认每页 5 条）",
                "需开启「个人能力系统」；偏逐条阅读，概览见 autonomy",
            ),
            (
                "/anima_capabilities_audit",
                "能力库健康体检：0 使用数、自封高分等",
                "需开启「个人能力系统」；偏运维诊断，列表见 capabilities",
            ),
            (
                "/anima_export_capabilities",
                "导出完整能力树 JSON 到数据目录",
                "需开启「个人能力系统」",
            ),
        ],
    ),
    (
        "高级 / 管理",
        [
            ("/anima_world_update", "手动触发世界观更新", "需开启「世界观系统」"),
            ("/anima_stability", "查看身份稳定度", "需开启「身份危机模块」"),
            ("/anima_reset", "重置自我认知（保留演化日志）", "⚠️ 破坏性操作"),
        ],
    ),
]


def render_help_text() -> str:
    lines = [
        "【Anima 指令帮助】",
        "",
        "发送 /anima_help 可随时查看本页。能力相关三条分工：",
        "  · autonomy = 概览  · capabilities = 详情  · capabilities_audit = 体检",
        "",
    ]
    for section, entries in HELP_SECTIONS:
        lines.append(f"── {section} ──")
        for cmd, summary, prereq in entries:
            line = f"  {cmd}\n    {summary}"
            if prereq:
                line += f"\n    （{prereq}）"
            lines.append(line)
        lines.append("")
    lines.append("配置项在 AstrBot WebUI → 插件 → Anima 中按 [核心]/[模型]/[可选模块]/[仪表盘]/[自主性]/[能力系统]/[高危] 分组浏览。")
    return "\n".join(lines).rstrip()
