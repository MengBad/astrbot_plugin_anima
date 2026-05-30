"""v0.9.6 embedding 可用性自检：通过/失败/未配置。"""
import sys
import types


def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m


_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})
_stub("astrbot.api.provider", {"LLMResponse": object, "ProviderRequest": object})

import asyncio  # noqa: E402
from anima.mixins.feedback import FeedbackMixin  # noqa: E402


class Host(FeedbackMixin):
    def __init__(self, config, embed_result=None, embed_raises=False):
        self.config = config
        self._embed_result = embed_result
        self._embed_raises = embed_raises

    async def _embed_one(self, text):
        if self._embed_raises:
            raise RuntimeError("provider down")
        return self._embed_result


class TestEmbeddingSelfCheck:
    def test_not_configured_returns_false(self):
        h = Host({})
        assert asyncio.run(h._check_embedding_availability()) is False

    def test_valid_vector_returns_true(self):
        h = Host({"embedding_provider_id": "p1"}, embed_result=[0.1, 0.2, 0.3])
        assert asyncio.run(h._check_embedding_availability()) is True

    def test_empty_vector_returns_false(self):
        h = Host({"embedding_provider_id": "p1"}, embed_result=[])
        assert asyncio.run(h._check_embedding_availability()) is False

    def test_none_returns_false(self):
        h = Host({"embedding_provider_id": "p1"}, embed_result=None)
        assert asyncio.run(h._check_embedding_availability()) is False

    def test_exception_returns_false(self):
        h = Host({"embedding_provider_id": "p1"}, embed_raises=True)
        assert asyncio.run(h._check_embedding_availability()) is False
