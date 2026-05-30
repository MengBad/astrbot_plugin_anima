"""
StandaloneDashboardServer —— v0.9.2 独立端口仪表盘 / v0.9.3 多页 + 导航
=================================================================

把 Anima 的 WebUI Plugin Pages 额外通过一个**独立 HTTP 端口**对外提供，满足"像别的
插件那样双击打开一个独立网址"的访问习惯。

v0.9.3：从单页（仅运行仪表盘）扩展为**多页 + 顶部导航**，把 AstrBot WebUI 里能看的
两个 Plugin Page 都搬上独立端口：
  - 运行仪表盘（dashboard）：今日各子系统运行统计
  - 能力树（capability-tree）：角色自创能力 + 自主演化事件
并接上 plugin_api.py 已有的全部只读数据接口（runtime_stats / stats / capabilities /
events / export / config）。

设计原则（安全优先，因为这是网络暴露的服务）：
- **默认关闭**（dashboard_standalone_enabled=false）。
- **默认只绑定 127.0.0.1**（仅本机可访问）。
- **强制 token 鉴权**：所有页面 / API 路由都要求 ?token=<token> 匹配（恒定时间比较），
  否则 401。token 通过 /anima_dashboard_url 命令获取。
- **零新依赖**：完全基于已有的 aiohttp。
- **复用前端**：直接读 pages/<page>/ 的三件套，不复制页面逻辑。通过注入一段极小的
  window.AstrBotPluginPage shim（支持 apiGet(path, params)）+ 顶部导航条，让既有
  app.js 原样工作。
- **复用数据层**：API 直接复用宿主插件已有的方法（plugin_api 的 helper 或插件自身方法），
  与 WebUI Plugin Page 返回完全一致的结构。
- **完全旁路**：服务启动/运行失败绝不影响插件主流程。
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from astrbot.api import logger

try:
    from aiohttp import web as _aiohttp_web
except Exception:  # pragma: no cover - aiohttp 是硬依赖，理论上不会缺
    _aiohttp_web = None


# 可用页面：page key -> (子目录名, 导航显示名)
_PAGES = {
    "dashboard": ("dashboard", "运行仪表盘"),
    "capability-tree": ("capability-tree", "能力树"),
}


def _bridge_shim() -> str:
    """注入到 <head> 的 bridge shim：让既有前端（依赖 window.AstrBotPluginPage）在独立
    端口下原样工作。apiGet 支持可选 params 对象（capability-tree 用 apiGet('events',
    {limit:20})），且统一打到绝对路径 /api/ 上（兼容子目录下的页面）。token 从当前
    页面 URL 的 query 读取并转手附加。"""
    return """
<script>
window.AstrBotPluginPage = {
  ready: function () { return Promise.resolve({}); },
  apiGet: function (path, params) {
    var q = new URLSearchParams();
    q.set('token', new URLSearchParams(location.search).get('token') || '');
    if (params) { for (var k in params) { q.set(k, params[k]); } }
    return fetch('/api/' + path + '?' + q.toString(), {
      headers: { 'Accept': 'application/json' }
    }).then(function (r) { return r.json(); });
  }
};
</script>
"""


def _nav_style() -> str:
    return """
<style>
.anima-nav{display:flex;align-items:center;gap:6px;flex-wrap:wrap;
  padding:10px 18px;background:#1e293b;position:sticky;top:0;z-index:999;
  box-shadow:0 1px 4px rgba(0,0,0,.25);font-family:-apple-system,BlinkMacSystemFont,
  "Segoe UI",Roboto,Arial,sans-serif;}
.anima-nav .brand{color:#818cf8;font-weight:800;font-size:16px;margin-right:14px;
  letter-spacing:.5px;}
.anima-nav a{color:#cbd5e1;text-decoration:none;padding:6px 14px;border-radius:8px;
  font-size:14px;transition:background .15s,color .15s;}
.anima-nav a:hover{background:#334155;color:#fff;}
.anima-nav a.active{background:#6366f1;color:#fff;}
</style>
"""


_UNAUTHORIZED_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Anima 仪表盘 · 未授权</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:80px auto;color:#334155">
<h2>401 未授权</h2>
<p>缺少或错误的访问 token。</p>
<p>在机器人聊天里发送 <code>/anima_dashboard_url</code> 获取带 token 的完整访问地址。</p>
</body></html>"""


class StandaloneDashboardServer:
    """独立端口仪表盘服务。依赖宿主插件提供 self.config / 数据方法。"""

    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self._runner = None
        self._site = None
        self.token: str = ""
        self.host: str = ""
        self.port: int = 0
        self.running: bool = False
        # pages 根目录（仓库根 / pages）
        self._pages_dir = Path(__file__).resolve().parent.parent / "pages"

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
        # 页面路由
        app.router.add_get("/", self._make_index_handler("dashboard"))
        app.router.add_get("/app.js", self._make_asset_handler("dashboard", "app.js"))
        app.router.add_get("/style.css", self._make_asset_handler("dashboard", "style.css"))
        app.router.add_get("/capability-tree", self._handle_captree_redirect)
        app.router.add_get("/capability-tree/", self._make_index_handler("capability-tree"))
        app.router.add_get(
            "/capability-tree/app.js", self._make_asset_handler("capability-tree", "app.js")
        )
        app.router.add_get(
            "/capability-tree/style.css", self._make_asset_handler("capability-tree", "style.css")
        )
        # 数据接口（只读，全部要求 token）
        app.router.add_get("/api/runtime_stats", self._handle_runtime_stats)
        app.router.add_get("/api/stats", self._handle_stats)
        app.router.add_get("/api/stats_history", self._handle_stats_history)
        app.router.add_get("/api/capabilities", self._handle_capabilities)
        app.router.add_get("/api/events", self._handle_events)
        app.router.add_get("/api/export", self._handle_export)
        app.router.add_get("/api/config", self._handle_config)

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

    def _read_asset(self, page: str, filename: str) -> Optional[str]:
        """读取 pages/<page>/<filename>。page 不在白名单则返回 None。"""
        if page not in _PAGES:
            return None
        subdir = _PAGES[page][0]
        try:
            path = self._pages_dir / subdir / filename
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[Anima] 读取页面 {page}/{filename} 失败: {e}")
            return None

    def _nav_html(self, active_page: str) -> str:
        """构造顶部导航条 HTML，链接带上 token，标注当前页 active。"""
        t = quote(self.token, safe="")
        links = []
        for key, (_subdir, label) in _PAGES.items():
            href = f"/?token={t}" if key == "dashboard" else f"/{key}/?token={t}"
            cls = "active" if key == active_page else ""
            links.append(f'<a href="{href}" class="{cls}">{label}</a>')
        return (
            '<nav class="anima-nav"><span class="brand">Anima</span>'
            + "".join(links)
            + "</nav>"
        )

    def _render_page(self, page: str) -> Optional[str]:
        """读取页面 index.html 并注入 bridge shim + 导航样式（head）与导航条（body）。"""
        html = self._read_asset(page, "index.html")
        if html is None:
            return None
        head_block = _bridge_shim() + _nav_style()
        if "</head>" in html:
            html = html.replace("</head>", head_block + "</head>", 1)
        else:
            html = head_block + html
        nav = self._nav_html(page)
        if "<body>" in html:
            html = html.replace("<body>", "<body>" + nav, 1)
        else:
            html = nav + html
        return html

    # 兼容旧测试：保留 _inject_shim 静态行为（注入 bridge shim 到 </head> 前）
    @staticmethod
    def _inject_shim(html: str) -> str:
        if "</head>" in html:
            return html.replace("</head>", _bridge_shim() + "</head>", 1)
        return _bridge_shim() + html

    # ── 数据层复用 ────────────────────────────────────────────────────────────

    def _caps_data(self) -> dict:
        """复用宿主的能力数据读取（优先 plugin_api helper，回退插件方法）。"""
        api = getattr(self.plugin, "plugin_api", None)
        if api is not None and hasattr(api, "_get_capabilities"):
            return api._get_capabilities()
        try:
            return self.plugin._read_personal_capabilities()
        except Exception as e:
            logger.error(f"[Anima] 读取能力数据失败: {e}")
            return {"capabilities": [], "error": str(e)}

    def _recent_events(self, limit: int) -> list:
        api = getattr(self.plugin, "plugin_api", None)
        if api is not None and hasattr(api, "_get_recent_events"):
            try:
                return api._get_recent_events(limit)
            except Exception as e:
                logger.error(f"[Anima] 读取演化事件失败: {e}")
                return []
        return []

    # ── 页面路由处理 ──────────────────────────────────────────────────────────

    def _make_index_handler(self, page: str):
        async def handler(request):
            if not self._check_token(request):
                return _aiohttp_web.Response(
                    status=401, text=_UNAUTHORIZED_HTML, content_type="text/html"
                )
            html = self._render_page(page)
            if html is None:
                return _aiohttp_web.Response(status=500, text=f"{page}/index.html 缺失")
            return _aiohttp_web.Response(text=html, content_type="text/html")
        return handler

    def _make_asset_handler(self, page: str, filename: str):
        content_type = (
            "application/javascript" if filename.endswith(".js") else "text/css"
        )

        async def handler(request):
            # 静态资源不含敏感数据，且页面已用 token 守门，这里不再强制 token，
            # 否则浏览器加载 ./app.js / ./style.css 不带 query 会被拦。
            body = self._read_asset(page, filename)
            if body is None:
                return _aiohttp_web.Response(status=404, text=f"{page}/{filename} 缺失")
            return _aiohttp_web.Response(text=body, content_type=content_type)
        return handler

    async def _handle_captree_redirect(self, request):
        """/capability-tree → /capability-tree/?token=...（保持相对资源路径正确）。"""
        t = quote(self.token, safe="")
        raise _aiohttp_web.HTTPFound(f"/capability-tree/?token={t}")

    # ── 数据接口处理（全部要求 token） ─────────────────────────────────────────

    def _unauthorized_json(self):
        return _aiohttp_web.json_response(
            {"success": False, "error": "unauthorized"}, status=401
        )

    async def _handle_runtime_stats(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
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

    async def _handle_stats(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
        try:
            caps = self._caps_data().get("capabilities", [])
            total = len(caps)
            avg_conf = sum(c.get("confidence", 0) for c in caps) / total if total > 0 else 0
            total_usage = sum(c.get("usage_count", 0) for c in caps)
            total_corrections = sum(len(c.get("corrections", [])) for c in caps)
            return _aiohttp_web.json_response({
                "success": True,
                "stats": {
                    "total_capabilities": total,
                    "average_confidence": round(avg_conf, 3),
                    "total_usage": total_usage,
                    "total_corrections": total_corrections,
                    "last_research": self._caps_data().get("last_research_ts"),
                },
            })
        except Exception as e:
            logger.error(f"[Anima] 独立端口获取能力统计失败: {e}")
            return _aiohttp_web.json_response({"success": False, "error": str(e)})

    async def _handle_stats_history(self, request):
        """v1.0.0: 返回历史趋势数据（近 N 天的 Daily_Snapshot 列表）。"""
        if not self._check_token(request):
            return self._unauthorized_json()
        try:
            history = self.plugin._get_stats_history()
            return _aiohttp_web.json_response({"success": True, "history": history})
        except Exception as e:
            logger.error(f"[Anima] 独立端口获取历史统计失败: {e}")
            return _aiohttp_web.json_response({"success": False, "error": str(e)})

    async def _handle_capabilities(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
        data = self._caps_data()
        return _aiohttp_web.json_response({
            "success": True,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })

    async def _handle_events(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
        try:
            limit = int(request.query.get("limit", 30))
        except (TypeError, ValueError):
            limit = 30
        events = self._recent_events(limit)
        return _aiohttp_web.json_response({
            "success": True,
            "events": events,
            "count": len(events),
        })

    async def _handle_export(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
        caps_data = self._caps_data()
        events = self._recent_events(50)
        export = {
            "exported_at": datetime.now().isoformat(),
            "plugin": "astrbot_plugin_anima",
            "capabilities": caps_data,
            "recent_autonomy_events": events,
        }
        return _aiohttp_web.json_response(export)

    async def _handle_config(self, request):
        if not self._check_token(request):
            return self._unauthorized_json()
        try:
            cfg = self.plugin.config
            keys_bool = [
                "autonomy_enabled", "autonomy_research_on_scar",
                "autonomy_research_on_time_absence", "autonomy_research_on_high_desire",
                "autonomy_research_on_personality_drift", "autonomy_research_on_contradiction",
                "capability_system_enabled", "default_register_as_independent_tool",
                "capability_health_pruning_enabled", "allow_capability_code_execution",
                "dynamic_tool_registration_enabled",
            ]
            autonomy_config = {k: cfg.get(k, None) for k in keys_bool}
            autonomy_config["code_execution_safety_level"] = cfg.get(
                "code_execution_safety_level", "strict"
            )
            return _aiohttp_web.json_response({"success": True, "config": autonomy_config})
        except Exception as e:
            logger.error(f"[Anima] 独立端口获取自主性配置失败: {e}")
            return _aiohttp_web.json_response({"success": False, "error": str(e)})
