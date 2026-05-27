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

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_capabilities(self) -> dict:
        try:
            return self.plugin._read_personal_capabilities()
        except Exception as e:
            logger.error(f"[Anima] 读取能力数据失败: {e}")
            return {"capabilities": [], "error": str(e)}

    def _get_recent_events(self, limit: int = 20) -> list[dict]:
        try:
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