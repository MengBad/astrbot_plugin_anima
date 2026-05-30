"""
StandaloneDashboardServer —— v0.9.2 独立端口仪表盘
=================================================

把运行仪表盘从 AstrBot WebUI 的 Plugin Pages 机制里"额外"再开一个**独立 HTTP 端口**
对外提供，满足"像别的插件那样双击打开一个独立网址"的访问习惯。

设计原则（安全优先，因为这是网络暴露的服务）：
- **默认关闭**（dashboard_standalone_enabled=false）。
- **默认只绑定 127.0.0.1**（仅本机可访问）。要远程访问需手动把 host 改成 0.0.0.0，
  配置项 hint 里明确警告。
- **强制 token 鉴权**：未配置 token 时启动自动生成一个随机 token，所有页面 / API
  路由都要求 ?token=<token> 匹配，否则 401。token 通过 /anima_dashboard_url 命令获取。
- **零新依赖**：完全基于已有的 aiohttp（requirements 已声明，main.py 已 import）。
- **复用前端**：直接读 pages/dashboard/ 的三件套，不复制一份仪表盘逻辑。通过注入一段
  极小的 window.AstrBotPluginPage shim，让既有 app.js 原样工作（它只用 ready()/apiGet()）。
- **完全旁路**：服务启动/运行失败绝不影响插件主流程（全异常吞掉 + 日志）。
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from astrbot.api import logger

try:
    from aiohttp import web as _aiohttp_web
except Exception:  # pragma: no cover - aiohttp 是硬依赖，理论上不会缺
    _aiohttp_web = None


# 注入到 index.html <head> 的 bridge shim：让既有前端（依赖 window.AstrBotPluginPage）
# 在独立端口下原样工作。token 从当前页面 URL 的 query 读取，转手附加到 API 请求上。
_BRIDGE_SHIM = """
<script>
window.AstrBotPluginPage = {
  ready: function () { return Promise.resolve(); },
  apiGet: function (path) {
    var t = new URLSearchParams(location.search).get('token') || '';
    return fetch('api/' + path + '?token=' + encodeURIComponent(t), {
      headers: { 'Accept': 'application/json' }
    }).then(function (r) { return r.json(); });
  }
};
</script>
"""

_UNAUTHORIZED_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Anima 仪表盘 · 未授权</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:80px auto;color:#334155">
<h2>401 未授权</h2>
<p>缺少或错误的访问 token。</p>
<p>在机器人聊天里发送 <code>/anima_dashboard_url</code> 获取带 token 的完整访问地址。</p>
</body></html>"""


class StandaloneDashboardServer:
    """独立端口仪表盘服务。依赖宿主插件提供 self.config / self._stats_snapshot()。"""

    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self._runner = None
        self._site = None
        self.token: str = ""
        self.host: str = ""
        self.port: int = 0
        self.running: bool = False
        # pages/dashboard 目录（仓库根 / pages / dashboard）
        self._pages_dir = Path(__file__).resolve().parent.parent / "pages" / "dashboard"

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """按配置启动独立端口服务。返回是否成功启动。"""
        if _aiohttp_web is None:
            logger.warning("[Anima] 独立端口仪表盘需要 aiohttp，但未能导入，已跳过")
            return False
        if self.running:
            return True

        cfg = self.plugin.config
        host = (cfg.get("dashboard_standalone_host", "127.0.0.1") or "127.0.0.1").strip()
        try:
            port = int(cfg.get("dashboard_standalone_port", 9876))
        except (TypeError, ValueError):
            port = 9876
        token = (cfg.get("dashboard_standalone_token", "") or "").strip()
        if not token:
            token = secrets.token_urlsafe(16)
        self.token = token

        app = _aiohttp_web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/app.js", self._handle_appjs)
        app.router.add_get("/style.css", self._handle_css)
        app.router.add_get("/api/runtime_stats", self._handle_runtime_stats)

        try:
            self._runner = _aiohttp_web.AppRunner(app)
            await self._runner.setup()
            self._site = _aiohttp_web.TCPSite(self._runner, host, port)
            await self._site.start()
        except OSError as e:
            logger.warning(
                f"[Anima] 独立端口仪表盘启动失败（{host}:{port} 可能被占用）: {e}"
            )
            await self._cleanup()
            return False
        except Exception as e:
            logger.warning(f"[Anima] 独立端口仪表盘启动异常: {e}")
            await self._cleanup()
            return False

        self.host = host
        self.port = port
        self.running = True
        if host not in ("127.0.0.1", "localhost"):
            logger.warning(
                f"[Anima] ⚠️ 独立端口仪表盘绑定到 {host}:{port}（非本机回环），"
                f"已对外暴露。仅靠 token 保护、且为明文 HTTP，请确保处于可信网络。"
            )
        logger.info(
            f"[Anima] 独立端口仪表盘已启动：{self.url()} "
            f"（用 /anima_dashboard_url 获取此地址）"
        )
        return True

    async def stop(self) -> None:
        """停止服务并清理。"""
        await self._cleanup()
        self.running = False

    async def _cleanup(self) -> None:
        try:
            if self._site is not None:
                await self._site.stop()
        except Exception:
            pass
        try:
            if self._runner is not None:
                await self._runner.cleanup()
        except Exception:
            pass
        self._site = None
        self._runner = None

    # ── 工具 ────────────────────────────────────────────────────────────────

    def url(self) -> str:
        """供命令展示的完整访问地址（含 token）。绑定 0.0.0.0 时回环地址给本机用。"""
        shown_host = "127.0.0.1" if self.host in ("0.0.0.0", "::", "") else self.host
        return f"http://{shown_host}:{self.port}/?token={self.token}"

    def _check_token(self, request) -> bool:
        # 恒定时间比较，避免公网暴露时的时序侧信道（v0.9.2）
        if not self.token:
            return False
        return secrets.compare_digest(request.query.get("token", ""), self.token)

    def _read_page(self, filename: str) -> Optional[str]:
        try:
            path = self._pages_dir / filename
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[Anima] 读取仪表盘页面 {filename} 失败: {e}")
            return None

    @staticmethod
    def _inject_shim(html: str) -> str:
        """把 bridge shim 注入到 </head> 之前（找不到则插到最前面）。"""
        if "</head>" in html:
            return html.replace("</head>", _BRIDGE_SHIM + "</head>", 1)
        return _BRIDGE_SHIM + html

    # ── 路由处理 ──────────────────────────────────────────────────────────────

    async def _handle_index(self, request):
        if not self._check_token(request):
            return _aiohttp_web.Response(
                status=401, text=_UNAUTHORIZED_HTML, content_type="text/html"
            )
        html = self._read_page("index.html")
        if html is None:
            return _aiohttp_web.Response(status=500, text="index.html 缺失")
        return _aiohttp_web.Response(
            text=self._inject_shim(html), content_type="text/html"
        )

    async def _handle_appjs(self, request):
        # 静态资源不含敏感数据，且页面已用 token 守门，这里不再强制 token，
        # 否则浏览器加载 ./app.js 不带 query 会被拦。
        js = self._read_page("app.js")
        if js is None:
            return _aiohttp_web.Response(status=404, text="app.js 缺失")
        return _aiohttp_web.Response(text=js, content_type="application/javascript")

    async def _handle_css(self, request):
        css = self._read_page("style.css")
        if css is None:
            return _aiohttp_web.Response(status=404, text="style.css 缺失")
        return _aiohttp_web.Response(text=css, content_type="text/css")

    async def _handle_runtime_stats(self, request):
        if not self._check_token(request):
            return _aiohttp_web.json_response(
                {"success": False, "error": "unauthorized"}, status=401
            )
        try:
            if not self.plugin.config.get("dashboard_enabled", True):
                return _aiohttp_web.json_response({
                    "success": False,
                    "disabled": True,
                    "error": "运行仪表盘已在插件配置中禁用（dashboard_enabled=false）",
                })
            snap = self.plugin._stats_snapshot()
            return _aiohttp_web.json_response({"success": True, "stats": snap})
        except Exception as e:
            logger.error(f"[Anima] 独立端口获取运行统计失败: {e}")
            return _aiohttp_web.json_response({"success": False, "error": str(e)})
