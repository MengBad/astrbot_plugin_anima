"""v0.9.5 Property 4: 自主网络抓取多标签提取且过滤脚本噪音。

直接测 _fetch_url 内部的 HTMLParser 提取逻辑——通过 mock aiohttp 的 session.get
注入固定 HTML，验证提取结果。由于测试环境 aiohttp 是桩，这里改为直接测提取器行为：
复刻 _fetch_url 的解析路径（同一份 _TextExtractor 逻辑）。
"""
import asyncio
import types

from _danger_host import DangerHost


HTML = """
<html><head><style>.x{color:red}</style><script>var a=1;</script></head>
<body>
<nav><div>导航栏</div></nav>
<h2>这是一个标题段落内容</h2>
<p>第一段正文内容比较长足够通过过滤</p>
<ul><li>列表项一足够长</li><li>列表项二足够长</li></ul>
<div>区块文字也应该被采集到的</div>
<script>console.log("应被过滤的脚本文本不计入");</script>
<style>body{margin:0;应被过滤的样式文本}</style>
</body></html>
"""


class _FakeResp:
    def __init__(self, html):
        self._html = html
    async def text(self):
        return self._html
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, html):
        self._html = html
    def get(self, url, headers=None, timeout=None):
        return _FakeResp(self._html)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False


def _run_fetch(host, html):
    # 把 danger 模块里的 aiohttp.ClientSession 临时替换为 fake
    import anima.mixins.danger as dmod
    orig = dmod.aiohttp
    dmod.aiohttp = types.SimpleNamespace(
        ClientSession=lambda: _FakeSession(html),
        ClientTimeout=lambda **kw: None,
    )
    try:
        return asyncio.run(host._fetch_url("http://x"))
    finally:
        dmod.aiohttp = orig


class TestFetchExtraction:
    def test_multi_tag_extracted(self):
        host = DangerHost(config={"autonomous_web_extract_chars": 1500})
        text = _run_fetch(host, HTML)
        assert "标题段落" in text       # h2
        assert "第一段正文" in text     # p
        assert "列表项一" in text       # li
        assert "区块文字" in text       # div

    def test_script_style_filtered(self):
        host = DangerHost(config={"autonomous_web_extract_chars": 1500})
        text = _run_fetch(host, HTML)
        assert "应被过滤的脚本文本" not in text
        assert "应被过滤的样式文本" not in text
        assert "var a=1" not in text

    def test_char_limit_enforced(self):
        host = DangerHost(config={"autonomous_web_extract_chars": 20})
        big = "<body>" + "".join(f"<p>很长的段落内容编号{i}</p>" for i in range(50)) + "</body>"
        text = _run_fetch(host, big)
        assert len(text) <= 20
