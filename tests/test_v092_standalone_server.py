"""测试 v0.9.2 独立端口仪表盘（StandaloneDashboardServer）。

测试环境没有安装 aiohttp（被其他测试 stub 掉），所以这里只测不依赖 aiohttp 的
纯逻辑：token 鉴权判定、bridge shim 注入、URL 构造、页面文件可读、缺 aiohttp 时
start() 安全降级。
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

from anima.standalone_server import StandaloneDashboardServer, _BRIDGE_SHIM


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
        assert _BRIDGE_SHIM in out
        # shim 必须在 </head> 之前
        assert out.index(_BRIDGE_SHIM) < out.index("</head>")

    def test_inject_without_head(self):
        html = "<body>no head here</body>"
        out = StandaloneDashboardServer._inject_shim(html)
        assert out.startswith(_BRIDGE_SHIM)

    def test_shim_defines_bridge(self):
        assert "window.AstrBotPluginPage" in _BRIDGE_SHIM
        assert "apiGet" in _BRIDGE_SHIM
        assert "ready" in _BRIDGE_SHIM


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
        html = s._read_page("index.html")
        js = s._read_page("app.js")
        css = s._read_page("style.css")
        assert html and "Anima" in html
        assert js and "loadDashboard" in js
        assert css is not None

    def test_missing_file_returns_none(self):
        s = _make()
        assert s._read_page("does_not_exist.html") is None

    def test_pages_dir_resolves(self):
        s = _make()
        assert s._pages_dir.name == "dashboard"
        assert (s._pages_dir / "index.html").exists()


class TestGracefulDegradation:
    async def _start(self, s):
        return await s.start()

    def test_start_returns_false_without_aiohttp(self):
        """测试环境无 aiohttp，start() 应安全返回 False，不抛异常。"""
        import asyncio
        import anima.standalone_server as mod
        # 测试环境本就没有 aiohttp（_aiohttp_web is None），直接验证
        assert mod._aiohttp_web is None
        s = _make({"dashboard_standalone_enabled": True})
        result = asyncio.run(s.start())
        assert result is False
        assert s.running is False

    def test_stop_is_safe_when_not_started(self):
        import asyncio
        s = _make()
        # 未启动时 stop() 不应抛异常
        asyncio.run(s.stop())
        assert s.running is False
