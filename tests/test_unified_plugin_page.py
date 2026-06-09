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
    assert 'plugin_root / "UI" / "plugin_pages" / page / "index.html"' in server
    assert 'plugin_root / "UI" / "plugin_pages" / page / filename' in server
    assert "_fallback_legacy_page_html" in server
    assert "/api/webui_manifest" in server


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


def test_shared_plugin_page_registers_anima_alias_for_astrbot_frontend_route():
    plugin_api = (ROOT / "plugin_api.py").read_text(encoding="utf-8")

    assert '("/anima", "page_handler", ["GET"])' in plugin_api
    assert '("/anima/", "page_handler", ["GET"])' in plugin_api
    assert '("/api/webui_manifest", "webui_manifest_handler", ["GET"])' in plugin_api


def test_astrbot_static_entry_does_not_auto_redirect_to_shared_route():
    html = (ROOT / "pages" / "anima" / "index.html").read_text(encoding="utf-8")

    assert "window.location.replace" not in html
    assert "runProbe()" in html
    assert "/anima_dashboard_url" in html
    assert "/astrbot_plugin_anima/health" in html


def test_stdlib_standalone_webui_accepts_query_token_and_observatory_routes():
    server = (ROOT / "anima" / "sylanne_alpha" / "webui_server.py").read_text(encoding="utf-8")

    assert 'token_val = auth[7:] if auth.startswith("Bearer ") else query.get("token", "")' in server
    assert "query = self._query()" in server
    assert "if not self._authorized(path, query):" in server
    assert 'elif path == "/api/mutation_rollback":' in server
    assert '"Rollback successful."' in server
    for route in (
        "/api/runtime_events",
        "/api/prompt_debug",
        "/api/state_inspector",
        "/api/state_store_audit",
        "/api/background_tasks",
        "/api/memory_explorer",
        "/api/memory_recall_replay",
        "/api/desire_dashboard",
        "/api/desire_evolution",
        "/api/scar_explorer",
        "/api/personality_drift",
        "/api/reasoning_trace",
        "/api/session_replay",
        "/api/mutation_history",
    ):
        assert f'path == "{route}"' in server
