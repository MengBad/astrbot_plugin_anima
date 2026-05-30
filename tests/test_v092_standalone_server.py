"""测试 v0.9.2/0.9.3 独立端口仪表盘（StandaloneDashboardServer）。

测试环境没有安装 aiohttp（被其他测试 stub 掉），所以这里只测不依赖 aiohttp 的
纯逻辑：token 鉴权判定、bridge shim 注入、URL 构造、多页文件可读、导航条、
页面渲染（注入 shim + 导航）、缺 aiohttp 时 start() 安全降级。
"""
import sys
import types
from pathlib import Path


def _stub(name, attrs=None):
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(
        **{k: lambda *a, **kw: None for k in ['debug', 'info', 'warning', 'error']}
    ),
})

from anima.standalone_server import StandaloneDashboardServer, _bridge_shim, _PAGES


class _FakePlugin:
    def __init__(self, config=None, snapshot=None):
        self.config = config or {}
        self._snap = snapshot or {"date": "2026-05-30", "llm_total": 0}

    def _stats_snapshot(self):
        return self._snap


def _make(config=None):
    return StandaloneDashboardServer(_FakePlugin(config or {}))


class _Req:
    """最小请求对象：只暴露 .query 字典。"""
    def __init__(self, query=None):
        self.query = query or {}


class TestTokenCheck:
    def test_matches_token(self):
        s = _make()
        s.token = "abc123"
        assert s._check_token(_Req({"token": "abc123"})) is True

    def test_rejects_wrong_token(self):
        s = _make()
        s.token = "abc123"
        assert s._check_token(_Req({"token": "nope"})) is False

    def test_rejects_missing_token(self):
        s = _make()
        s.token = "abc123"
        assert s._check_token(_Req({})) is False

    def test_rejects_when_no_token_set(self):
        """token 未设置时一律拒绝（避免空 token 等于放行）。"""
        s = _make()
        s.token = ""
        assert s._check_token(_Req({"token": ""})) is False


class TestShimInjection:
    def test_inject_before_head_close(self):
        html = "<html><head><title>x</title></head><body></body></html>"
        out = StandaloneDashboardServer._inject_shim(html)
        shim = _bridge_shim()
        assert shim in out
        # shim 必须在 </head> 之前
        assert out.index(shim) < out.index("</head>")

    def test_inject_without_head(self):
        html = "<body>no head here</body>"
        out = StandaloneDashboardServer._inject_shim(html)
        assert out.startswith(_bridge_shim())

    def test_shim_defines_bridge(self):
        shim = _bridge_shim()
        assert "window.AstrBotPluginPage" in shim
        assert "apiGet" in shim
        assert "ready" in shim

    def test_shim_apiget_supports_params(self):
        """apiGet 必须支持第二个 params 参数（capability-tree 用 apiGet('events',{limit:20})）。"""
        shim = _bridge_shim()
        assert "params" in shim
        # 统一打到绝对 /api/ 路径
        assert "'/api/'" in shim


class TestUrl:
    def test_url_contains_host_port_token(self):
        s = _make()
        s.host, s.port, s.token = "127.0.0.1", 9876, "tok"
        assert s.url() == "http://127.0.0.1:9876/?token=tok"

    def test_url_maps_wildcard_to_loopback(self):
        """绑定 0.0.0.0 时，展示给用户的地址用回环地址（本机可直接打开）。"""
        s = _make()
        s.host, s.port, s.token = "0.0.0.0", 8080, "tok"
        assert s.url() == "http://127.0.0.1:8080/?token=tok"


class TestPageFiles:
    def test_reads_real_dashboard_files(self):
        """复用 pages/dashboard 的真实三件套，确认可读。"""
        s = _make()
        html = s._read_asset("dashboard", "index.html")
        js = s._read_asset("dashboard", "app.js")
        css = s._read_asset("dashboard", "style.css")
        assert html and "Anima" in html
        assert js and "loadDashboard" in js
        assert css is not None

    def test_reads_real_capability_tree_files(self):
        """v0.9.3：能力树三件套也要能读。"""
        s = _make()
        html = s._read_asset("capability-tree", "index.html")
        js = s._read_asset("capability-tree", "app.js")
        css = s._read_asset("capability-tree", "style.css")
        assert html and "能力树" in html
        assert js and "loadCapabilities" in js
        assert css is not None

    def test_unknown_page_returns_none(self):
        s = _make()
        assert s._read_asset("evil-page", "index.html") is None

    def test_missing_file_returns_none(self):
        s = _make()
        assert s._read_asset("dashboard", "does_not_exist.html") is None

    def test_pages_dir_resolves(self):
        s = _make()
        assert s._pages_dir.name == "pages"
        assert (s._pages_dir / "dashboard" / "index.html").exists()
        assert (s._pages_dir / "capability-tree" / "index.html").exists()


class TestNavAndRender:
    def test_nav_lists_all_pages_with_token(self):
        s = _make()
        s.token = "tok"
        nav = s._nav_html("dashboard")
        # 两个页面都在导航里
        for key, (_subdir, label) in _PAGES.items():
            assert label in nav
        # 带 token
        assert "token=tok" in nav
        # 当前页 active
        assert 'class="active"' in nav

    def test_render_page_injects_shim_and_nav(self):
        s = _make()
        s.token = "tok"
        html = s._render_page("dashboard")
        assert html is not None
        # 注入了 bridge shim
        assert "window.AstrBotPluginPage" in html
        # 注入了导航条
        assert "anima-nav" in html
        # 导航条元素紧跟在 body 之后（<nav class="anima-nav"> 出现在 body 内）
        assert '<body><nav class="anima-nav">' in html

    def test_render_capability_tree_page(self):
        s = _make()
        s.token = "tok"
        html = s._render_page("capability-tree")
        assert html is not None
        assert "能力树" in html
        assert "anima-nav" in html

    def test_render_unknown_page_returns_none(self):
        s = _make()
        assert s._render_page("nope") is None


class TestGracefulDegradation:
    def test_start_returns_false_without_aiohttp(self):
        """测试环境无 aiohttp，start() 应安全返回 False，不抛异常。"""
        import asyncio
        import anima.standalone_server as mod
        assert mod._aiohttp_web is None
        s = _make({"dashboard_standalone_enabled": True})
        result = asyncio.run(s.start())
        assert result is False
        assert s.running is False

    def test_stop_is_safe_when_not_started(self):
        import asyncio
        s = _make()
        asyncio.run(s.stop())
        assert s.running is False
