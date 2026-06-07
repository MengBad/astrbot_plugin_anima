"""Cognitive Timeline WebUI contract tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_portal_exposes_cognitive_timeline_panel():
    html = (ROOT / "anima" / "UI" / "portal.html").read_text(encoding="utf-8")

    assert "tab-cognitive" in html
    assert "panel-cognitive" in html
    assert "loadCognitiveTimeline" in html
    assert "/api/runtime_events" in html
    assert "Cognitive Timeline" in html
    assert "state-inspector-card" in html
    assert "loadStateInspector" in html
    assert "/api/state_inspector" in html
    assert "State Inspector" in html
    assert "memory-explorer-card" in html
    assert "loadMemoryExplorer" in html
    assert "/api/memory_explorer" in html
    assert "Memory Explorer" in html
    assert "desire-dashboard-card" in html
    assert "loadDesireDashboard" in html
    assert "/api/desire_dashboard" in html
    assert "Desire Dashboard" in html
    assert "scar-explorer-card" in html
    assert "loadScarExplorer" in html
    assert "/api/scar_explorer" in html
    assert "Scar Explorer" in html
    assert "personality-drift-card" in html
    assert "loadPersonalityDrift" in html
    assert "/api/personality_drift" in html
    assert "Personality Drift" in html


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


def test_memory_explorer_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/memory_explorer", "memory_explorer_handler", ["GET"])' in plugin_api
    assert "async def memory_explorer_handler" in shared_routes
    assert 'app.router.add_get("/api/memory_explorer", handle_memory_explorer)' in independent_server


def test_desire_dashboard_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/desire_dashboard", "desire_dashboard_handler", ["GET"])' in plugin_api
    assert "async def desire_dashboard_handler" in shared_routes
    assert 'app.router.add_get("/api/desire_dashboard", handle_desire_dashboard)' in independent_server


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
