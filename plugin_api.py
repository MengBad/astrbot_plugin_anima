import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from quart import jsonify, request

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_anima"


class PluginAPI:
    """Backend API provider for Anima's Plugin Pages (capability tree & autonomy panel)."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def register(self, context) -> None:
        """Register all web API routes. Must be called in __init__ of the main plugin."""
        routes = [
            ("/capabilities", "handle_get_capabilities", ["GET"]),
            ("/events", "handle_get_events", ["GET"]),
            ("/stats", "handle_get_stats", ["GET"]),
            ("/runtime_stats", "handle_get_runtime_stats", ["GET"]),
            ("/stats_history", "handle_get_stats_history", ["GET"]),
            ("/export", "handle_export", ["GET"]),
            ("/config", "handle_get_autonomy_config", ["GET"]),
        ]
        for route, handler_name, methods in routes:
            handler = getattr(self, handler_name)
            context.register_web_api(
                f"/{PLUGIN_NAME}{route}",
                handler,
                methods,
                f"Anima Plugin Page: {handler_name}",
            )
        logger.info("[Anima] Plugin Pages API 已注册")

        # ── 注册 Sylanne WebUI 路由到 AstrBot 共享端口 ───────────────────────────
        webui_routes = getattr(self.plugin, "_webui_routes", None)
        if webui_routes:
            webui_mappings = [
                ("", "page_handler", ["GET"]),
                ("/anima", "page_handler", ["GET"]),
                ("/anima/", "page_handler", ["GET"]),
                ("/sylanne", "sylanne_page_handler", ["GET"]),
                ("/sylanne/", "sylanne_page_handler", ["GET"]),
                ("/dashboard", "dashboard_handler", ["GET"]),
                ("/dashboard/", "dashboard_handler", ["GET"]),
                ("/dashboard/app.js", "dashboard_asset_js_handler", ["GET"]),
                ("/dashboard/style.css", "dashboard_asset_css_handler", ["GET"]),
                ("/capability-tree", "capability_tree_handler", ["GET"]),
                ("/capability-tree/", "capability_tree_handler", ["GET"]),
                ("/capability-tree/app.js", "capability_tree_asset_js_handler", ["GET"]),
                ("/capability-tree/style.css", "capability_tree_asset_css_handler", ["GET"]),
                ("/logo.png", "logo_handler", ["GET"]),
                ("/health", "health_handler", ["GET"]),
                ("/api/state", "state_handler", ["GET"]),
                ("/api/mutation_history", "mutation_history_handler", ["GET"]),
                ("/api/mutation_rollback", "mutation_rollback_handler", ["POST"]),
                ("/api/settings", "settings_get_handler", ["GET"]),
                ("/api/settings", "settings_post_handler", ["POST"]),
                ("/api/computation_logs", "computation_logs_handler", ["GET"]),
                ("/api/runtime_events", "runtime_events_handler", ["GET"]),
                ("/api/prompt_debug", "prompt_debug_handler", ["GET"]),
                ("/api/reasoning_trace", "reasoning_trace_handler", ["GET"]),
                ("/api/session_replay", "session_replay_handler", ["GET"]),
                ("/api/state_inspector", "state_inspector_handler", ["GET"]),
                ("/api/state_store_audit", "state_store_audit_handler", ["GET"]),
                ("/api/background_tasks", "background_tasks_handler", ["GET"]),
                ("/api/webui_manifest", "webui_manifest_handler", ["GET"]),
                ("/api/memory_explorer", "memory_explorer_handler", ["GET"]),
                ("/api/memory_recall_replay", "memory_recall_replay_handler", ["GET"]),
                ("/api/desire_dashboard", "desire_dashboard_handler", ["GET"]),
                ("/api/desire_evolution", "desire_evolution_handler", ["GET"]),
                ("/api/scar_explorer", "scar_explorer_handler", ["GET"]),
                ("/api/personality_drift", "personality_drift_handler", ["GET"]),
                ("/api/memory_pools", "memory_pools_handler", ["GET"]),
                ("/api/memory_meltdown", "memory_meltdown_handler", ["POST"]),
                ("/api/meltdown_nonce", "meltdown_nonce_handler", ["GET"]),
                ("/api/memory_consolidate", "memory_consolidate_handler", ["POST"]),
                ("/api/memory_sink", "memory_sink_handler", ["GET"]),
                ("/api/config_presets", "config_presets_handler", ["GET"]),
                ("/api/glossary", "glossary_handler", ["GET"]),
                ("/api/export_data", "export_data_handler", ["GET"]),
                ("/api/purge_data", "purge_data_handler", ["DELETE"]),
                ("/api/webui_probe", "probe_handler", ["GET"]),
                ("/api/error_stats", "error_stats_handler", ["GET"]),
                ("/api/config_export", "config_export_handler", ["GET"]),
                ("/api/config_import", "config_import_handler", ["POST"]),
                ("/api/widget-state", "widget_state_handler", ["GET"]),
                ("/api/proactive_feedback", "proactive_feedback_handler", ["POST"]),
                ("/api/weekly_report", "weekly_report_handler", ["GET"]),
                ("/api/memory/decay_curve", "memory_decay_curve_handler", ["GET"]),
                ("/api/personality/export", "personality_export_handler", ["GET"]),
                ("/api/personality/import", "personality_import_handler", ["POST"]),
                ("/api/memory_settings", "memory_settings_get_handler", ["GET"]),
                ("/api/memory_settings", "memory_settings_post_handler", ["POST"]),
                ("/api/lineage_observatory", "lineage_observatory_handler", ["GET"]),
            ]
            for route, handler_name, methods in webui_mappings:
                handler = getattr(webui_routes, handler_name, None)
                if handler:
                    context.register_web_api(
                        f"/{PLUGIN_NAME}{route}",
                        handler,
                        methods,
                        f"Anima WebUI: {handler_name}",
                    )
            logger.info("[Anima] Sylanne WebUI 路由已注册到 AstrBot 共享端口")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_capabilities(self) -> dict:
        try:
            return self.plugin._read_personal_capabilities()
        except Exception as e:
            logger.error(f"[Anima] 读取能力数据失败: {e}")
            return {"capabilities": [], "error": str(e)}

    def _get_recent_events(self, limit: int = 20) -> list[dict]:
        try:
            bus = getattr(self.plugin, "_runtime_event_bus", None)
            if bus is not None and hasattr(bus, "recent"):
                events = bus.recent(limit=limit)
                if events:
                    return events
            logs = self.plugin._read_evolution_log(limit * 2)  # 多读一些过滤
            keywords = ["autonomous", "capability", "self_directed", "dynamic", "pruning", "gap", "mutation"]
            filtered = []
            for log in logs:
                trigger = str(log.get("trigger", "")).lower()
                content = str(log.get("new_content", "")).lower()
                if any(kw in trigger or kw in content for kw in keywords):
                    filtered.append(log)
                if len(filtered) >= limit:
                    break
            return filtered
        except Exception as e:
            logger.error(f"[Anima] 读取演化事件失败: {e}")
            return []

    # ── API Handlers ─────────────────────────────────────────────────────────

    async def handle_get_capabilities(self):
        """返回完整的能力树数据"""
        data = self._get_capabilities()
        return jsonify({
            "success": True,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })

    async def handle_get_events(self):
        """返回最近的自主演化事件"""
        limit = request.args.get("limit", 30, type=int)
        events = self._get_recent_events(limit)
        return jsonify({
            "success": True,
            "events": events,
            "count": len(events)
        })

    async def handle_get_stats(self):
        """返回能力系统统计"""
        caps = self._get_capabilities().get("capabilities", [])
        total = len(caps)
        avg_conf = sum(c.get("confidence", 0) for c in caps) / total if total > 0 else 0
        total_usage = sum(c.get("usage_count", 0) for c in caps)
        total_corrections = sum(len(c.get("corrections", [])) for c in caps)

        return jsonify({
            "success": True,
            "stats": {
                "total_capabilities": total,
                "average_confidence": round(avg_conf, 3),
                "total_usage": total_usage,
                "total_corrections": total_corrections,
                "last_research": self._get_capabilities().get("last_research_ts")
            }
        })

    async def handle_get_runtime_stats(self):
        """v0.9.1: 返回今日运行统计快照（LLM 调用 / 沉淀 / 主动发言拦截 / 存储），
        供运行仪表盘网页消费。
        v0.9.1: 受 dashboard_enabled 开关控制（默认开）。"""
        try:
            if not self.plugin.config.get("dashboard_enabled", True):
                return jsonify({
                    "success": False,
                    "disabled": True,
                    "error": "运行仪表盘已在插件配置中禁用（请开启「运行仪表盘」）",
                })
            snap = self.plugin._stats_snapshot()
            return jsonify({"success": True, "stats": snap})
        except Exception as e:
            logger.error(f"[Anima] 获取运行统计失败: {e}")
            return jsonify({"success": False, "error": str(e)})

    async def handle_get_stats_history(self):
        """v1.0.0: 返回历史趋势归档（供 WebUI 仪表盘 apiGet('stats_history')）。"""
        try:
            if not self.plugin.config.get("dashboard_enabled", True):
                return jsonify({
                    "success": False,
                    "disabled": True,
                    "error": "运行仪表盘已在插件配置中禁用（请开启「运行仪表盘」）",
                })
            history = self.plugin._get_stats_history()
            return jsonify({"success": True, "history": history})
        except Exception as e:
            logger.error(f"[Anima] 获取历史统计失败: {e}")
            return jsonify({"success": False, "error": str(e)})

    async def handle_export(self):
        """导出完整能力树 JSON（带统计）"""
        caps_data = self._get_capabilities()
        events = self._get_recent_events(50)

        export = {
            "exported_at": datetime.now().isoformat(),
            "plugin": "astrbot_plugin_anima",
            "version": "0.6.0-dev",
            "capabilities": caps_data,
            "recent_autonomy_events": events
        }
        return jsonify(export)

    async def handle_get_autonomy_config(self):
        """返回与 v0.6+ 自主性相关的配置（供 WebUI 面板展示）"""
        try:
            cfg = self.plugin.config
            autonomy_config = {
                "autonomy_enabled": cfg.get("autonomy_enabled", True),
                "autonomy_research_on_scar": cfg.get("autonomy_research_on_scar", True),
                "autonomy_research_on_time_absence": cfg.get("autonomy_research_on_time_absence", True),
                "autonomy_research_on_high_desire": cfg.get("autonomy_research_on_high_desire", True),
                "autonomy_research_on_personality_drift": cfg.get("autonomy_research_on_personality_drift", True),
                "autonomy_research_on_contradiction": cfg.get("autonomy_research_on_contradiction", True),

                "capability_system_enabled": cfg.get("capability_system_enabled", True),
                "default_register_as_independent_tool": cfg.get("default_register_as_independent_tool", False),
                "capability_health_pruning_enabled": cfg.get("capability_health_pruning_enabled", True),

                "allow_capability_code_execution": cfg.get("allow_capability_code_execution", False),
                "code_execution_safety_level": cfg.get("code_execution_safety_level", "strict"),

                "dynamic_tool_registration_enabled": cfg.get("dynamic_tool_registration_enabled", False),
            }
            return jsonify({"success": True, "config": autonomy_config})
        except Exception as e:
            logger.error(f"获取自主性配置失败: {e}")
            return jsonify({"success": False, "error": str(e)})


# 注意：需要在 main.py 的 __init__ 中调用：
# self.plugin_api = PluginAPI(self)
# self.plugin_api.register(context)
