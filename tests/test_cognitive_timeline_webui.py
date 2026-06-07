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


def test_runtime_events_route_registered_in_both_webui_layers():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    independent_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert '("/api/runtime_events", "runtime_events_handler", ["GET"])' in plugin_api
    assert "async def runtime_events_handler" in shared_routes
    assert 'app.router.add_get("/api/runtime_events", handle_runtime_events)' in independent_server
