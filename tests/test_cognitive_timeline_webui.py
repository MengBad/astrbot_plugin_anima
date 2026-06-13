"""Cognitive Timeline WebUI contract tests."""

import asyncio
import os
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_portal_exposes_cognitive_timeline_panel():
    html = (ROOT / "anima" / "UI" / "portal.html").read_text(encoding="utf-8")

    assert "view-observatory" in html
    assert "loadTimeline" in html
    assert "/api/runtime_events" in html
    assert "认知观测台" in html
    assert "loadInspector" in html
    assert "/api/state_inspector" in html
    assert "状态检查" in html
    assert "state_store_audit" in html
    assert "存储源" in html
    assert "StateStore" in html
    assert "loadStore" in html
    assert "/api/state_store_audit" in html
    assert "loadTasks" in html
    assert "/api/background_tasks" in html
    assert "后台任务" in html
    assert "loadMemory" in html
    assert "/api/memory_explorer" in html
    assert "记忆探索" in html
    assert "/api/memory_recall_replay" in html
    assert "记忆召回回放" in html
    assert "loadDesire" in html
    assert "/api/desire_dashboard" in html
    assert "欲望系统" in html
    assert "/api/desire_evolution" in html
    assert "loadScar" in html
    assert "/api/scar_explorer" in html
    assert "创伤浏览器" in html
    assert "loadDrift" in html
    assert "/api/personality_drift" in html
    assert "人格漂移" in html
    assert "loadTrace" in html
    assert "/api/reasoning_trace" in html
    assert "推理轨迹" in html
    assert "loadReplay" in html
    assert "/api/session_replay" in html
    assert "会话回放" in html
    assert "loadTrend" in html
    assert "/api/cross_session_trend" in html
    assert "跨会话趋势" in html
    assert "searchEvents" in html
    assert "/api/event_search" in html
    assert "createSnapshot" in html
    assert "/api/state_snapshot" in html
    assert "loadSnapshots" in html
    assert "/api/snapshot_list" in html
    assert "rollbackSnapshot" in html
    assert "/api/state_rollback" in html
    assert "deleteSnapshot" in html
    assert "/api/snapshot_delete" in html


def test_portal_uses_route_base_for_shared_astrbot_webui_fetches():
    html = (ROOT / "anima" / "UI" / "portal.html").read_text(encoding="utf-8")

    assert "window.location.pathname.startsWith('/astrbot_plugin_anima')" in html
    assert "function rp(p)" in html
    assert "rp('/sylanne/" in html
    assert "rp('/dashboard/" in html
    assert "rp('/capability-tree/" in html
    assert "rp('/api/state" in html
    assert "rp('/api/runtime_events" in html
    assert "rp('/api/session_replay" in html
    assert "fetch(`/api/" not in html
    assert "fetch('/api/" not in html


def test_runtime_events_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/runtime_events", "runtime_events_handler", ["GET"])' in plugin_api
    assert "async def runtime_events_handler" in shared_routes
    assert 'app.router.add_get("/api/runtime_events", handle_runtime_events)' in independent_server


def test_prompt_debug_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/prompt_debug", "prompt_debug_handler", ["GET"])' in plugin_api
    assert "async def prompt_debug_handler" in shared_routes
    assert 'app.router.add_get("/api/prompt_debug", handle_prompt_debug)' in independent_server


def test_state_inspector_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/state_inspector", "state_inspector_handler", ["GET"])' in plugin_api
    assert "async def state_inspector_handler" in shared_routes
    assert 'app.router.add_get("/api/state_inspector", handle_state_inspector)' in independent_server


def test_state_store_audit_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/state_store_audit", "state_store_audit_handler", ["GET"])' in plugin_api
    assert "async def state_store_audit_handler" in shared_routes
    assert 'app.router.add_get("/api/state_store_audit", handle_state_store_audit)' in independent_server


def test_background_tasks_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/background_tasks", "background_tasks_handler", ["GET"])' in plugin_api
    assert "async def background_tasks_handler" in shared_routes
    assert 'app.router.add_get("/api/background_tasks", handle_background_tasks)' in independent_server


def test_webui_manifest_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/webui_manifest", "webui_manifest_handler", ["GET"])' in plugin_api
    assert "async def webui_manifest_handler" in shared_routes
    assert 'app.router.add_get("/api/webui_manifest", handle_webui_manifest)' in independent_server


def test_memory_explorer_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/memory_explorer", "memory_explorer_handler", ["GET"])' in plugin_api
    assert "async def memory_explorer_handler" in shared_routes
    assert 'app.router.add_get("/api/memory_explorer", handle_memory_explorer)' in independent_server


def test_memory_recall_replay_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/memory_recall_replay", "memory_recall_replay_handler", ["GET"])' in plugin_api
    assert "async def memory_recall_replay_handler" in shared_routes
    assert 'app.router.add_get("/api/memory_recall_replay", handle_memory_recall_replay)' in independent_server


def test_desire_dashboard_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/desire_dashboard", "desire_dashboard_handler", ["GET"])' in plugin_api
    assert "async def desire_dashboard_handler" in shared_routes
    assert 'app.router.add_get("/api/desire_dashboard", handle_desire_dashboard)' in independent_server


def test_desire_evolution_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/desire_evolution", "desire_evolution_handler", ["GET"])' in plugin_api
    assert "async def desire_evolution_handler" in shared_routes
    assert 'app.router.add_get("/api/desire_evolution", handle_desire_evolution)' in independent_server


def test_scar_explorer_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/scar_explorer", "scar_explorer_handler", ["GET"])' in plugin_api
    assert "async def scar_explorer_handler" in shared_routes
    assert 'app.router.add_get("/api/scar_explorer", handle_scar_explorer)' in independent_server


def test_personality_drift_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/personality_drift", "personality_drift_handler", ["GET"])' in plugin_api
    assert "async def personality_drift_handler" in shared_routes
    assert 'app.router.add_get("/api/personality_drift", handle_personality_drift)' in independent_server


def test_reasoning_trace_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/reasoning_trace", "reasoning_trace_handler", ["GET"])' in plugin_api
    assert "async def reasoning_trace_handler" in shared_routes
    assert 'app.router.add_get("/api/reasoning_trace", handle_reasoning_trace)' in independent_server


def test_session_replay_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/session_replay", "session_replay_handler", ["GET"])' in plugin_api
    assert "async def session_replay_handler" in shared_routes
    assert 'app.router.add_get("/api/session_replay", handle_session_replay)' in independent_server


def test_shared_webui_registers_portal_iframe_pages_and_assets():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")

    for route, handler in [
        ("/sylanne/", "sylanne_page_handler"),
        ("/dashboard/", "dashboard_handler"),
        ("/dashboard/app.js", "dashboard_asset_js_handler"),
        ("/dashboard/style.css", "dashboard_asset_css_handler"),
        ("/capability-tree/", "capability_tree_handler"),
        ("/capability-tree/app.js", "capability_tree_asset_js_handler"),
        ("/capability-tree/style.css", "capability_tree_asset_css_handler"),
    ]:
        assert f'("{route}", "{handler}", ["GET"])' in plugin_api
        assert f"async def {handler}" in shared_routes

    assert "window.AstrBotPluginPage = {" in shared_routes
    assert "routeBase() + '/' + path" in shared_routes


def test_mutation_routes_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/mutation_history", "mutation_history_handler", ["GET"])' in plugin_api
    assert '("/api/mutation_rollback", "mutation_rollback_handler", ["POST"])' in plugin_api
    assert "async def mutation_history_handler" in shared_routes
    assert "async def mutation_rollback_handler" in shared_routes
    assert "build_redacted_mutation_history" in shared_routes
    assert "build_redacted_mutation_history" in independent_server
    assert "_atomic_write_text_locked" in shared_routes
    assert "_atomic_write_text_locked" in independent_server
    assert 'app.router.add_get("/api/mutation_history", handle_mutation_history)' in independent_server
    assert 'app.router.add_post("/api/mutation_rollback", handle_mutation_rollback)' in independent_server


def test_mutation_history_webui_projection_redacts_descriptions():
    sys.path.insert(0, str(ROOT / "anima"))
    from sylanne_alpha.mutation_history_view import build_redacted_mutation_history

    secret = "core_beliefs: user-private persona fragment"
    noisy_type = "belief_shift:" + ("x" * 200)
    noisy_trigger = "sediment:" + ("y" * 200)
    payload = build_redacted_mutation_history(
        {
            "mutation_history": [
                {
                    "timestamp": "2026-06-08T00:00:00" + ("z" * 200),
                    "type": noisy_type,
                    "description": secret,
                    "triggered_by": noisy_trigger,
                }
            ]
        },
        limit=10,
    )

    assert payload["ok"] is True
    assert payload["schema_version"] == "anima.mutation_history.v1"
    assert payload["count"] == 1
    item = payload["history"][0]
    assert item["description_redacted"] is True
    assert item["description_length"] == len(secret)
    assert item["description_fingerprint"]
    assert len(item["timestamp"]) <= 40
    assert len(item["type"]) <= 64
    assert len(item["triggered_by"]) <= 64
    assert "description" not in item
    assert secret not in str(payload)
    assert noisy_type not in str(payload)
    assert noisy_trigger not in str(payload)


def test_portal_renders_redacted_mutation_history_metadata():
    html = (ROOT / "anima" / "UI" / "portal.html").read_text(encoding="utf-8")

    assert "description_redacted" in html
    assert "description_length" in html
    assert "description_fingerprint" in html
    assert "描述已脱敏" in html


def test_shared_mutation_rollback_swaps_persona_files_atomically(tmp_path):
    sys.path.insert(0, str(ROOT / "anima"))
    from anima.sylanne_alpha.webui_routes import WebUIRoutes

    persona_path = tmp_path / "persona_core.yaml"
    backup_path = tmp_path / "persona_core.yaml.bak"
    persona_path.write_text("current persona", encoding="utf-8")
    backup_path.write_text("backup persona", encoding="utf-8")

    class DummyPlugin:
        def __init__(self) -> None:
            self.config = {"persona_lock": False}
            self.persona_core_path = str(persona_path)
            self._io_lock = threading.RLock()
            self.atomic_writes: list[str] = []
            self.mutations: list[tuple[str, str, str]] = []

        def _atomic_write_text_locked(self, path: str, content: str) -> None:
            self.atomic_writes.append(os.path.basename(path))
            tmp = f"{path}.tmp"
            Path(tmp).write_text(content, encoding="utf-8")
            os.replace(tmp, path)

        def _record_mutation(self, mutation_type: str, description: str, *, triggered_by: str) -> None:
            self.mutations.append((mutation_type, description, triggered_by))

    plugin = DummyPlugin()
    result = asyncio.run(WebUIRoutes(plugin).mutation_rollback_handler())

    assert result == {"ok": True, "message": "Rollback successful."}
    assert persona_path.read_text(encoding="utf-8") == "backup persona"
    assert backup_path.read_text(encoding="utf-8") == "current persona"
    assert plugin.atomic_writes == ["persona_core.yaml", "persona_core.yaml.bak"]
    assert plugin.mutations == [
        (
            "回滚恢复",
            "用户手动触发回滚：已恢复上一版本的核心人设配置。",
            "user_webui",
        )
    ]
