"""Unified AstrBot Plugin Page entry tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_astrbot_plugin_pages_expose_single_unified_entry():
    pages_dir = ROOT / "pages"
    entries = sorted(path.name for path in pages_dir.iterdir() if path.is_dir())

    assert entries == ["anima"]
    assert (pages_dir / "anima" / "index.html").exists()


def test_legacy_page_assets_are_kept_for_internal_webui_routes():
    internal = ROOT / "anima" / "UI" / "plugin_pages"

    for page in ("capability-tree", "dashboard"):
        page_dir = internal / page
        assert (page_dir / "index.html").exists()
        assert (page_dir / "app.js").exists()
        assert (page_dir / "style.css").exists()


def test_standalone_webui_reads_legacy_assets_from_internal_directory():
    server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert 'return plugin_root / "UI" / "plugin_pages"' in server
    assert 'app.router.add_get("/capability-tree/", handle_captree_index)' in server
    assert 'app.router.add_get("/dashboard/", handle_dashboard_index)' in server


def test_legacy_iframe_bridge_paths_match_hosting_layer_contract():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")
    shared_routes = (ROOT / "anima" / "sylanne_alpha" / "webui_routes.py").read_text(encoding="utf-8")
    standalone_server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    for route in ("/stats", "/runtime_stats", "/stats_history", "/capabilities", "/events", "/export"):
        assert f'("{route}", ' in plugin_api

    for route in ("/api/stats", "/api/runtime_stats", "/api/stats_history", "/api/capabilities", "/api/events"):
        assert f'app.router.add_get("{route}", ' in standalone_server

    assert "routeBase() + '/' + path" in shared_routes
    assert "return fetch('/api/' + path" in standalone_server
