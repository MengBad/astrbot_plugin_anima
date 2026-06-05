import sys
import types

def _stub(name, attrs=None):
    m = types.ModuleType(name); m.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m

_stub("astrbot")
_stub("astrbot.api", {
    "logger": types.SimpleNamespace(
        **{k: (lambda *a, **kw: None) for k in ['debug', 'info', 'warning', 'error']}
    ),
    "AstrBotConfig": dict,
})
_stub("astrbot.api.event", {"filter": types.SimpleNamespace(), "AstrMessageEvent": object})

from anima.mixins.desire import DesireMixin

class MockDesireHost(DesireMixin):
    def __init__(self, config=None):
        self.config = config or {}

def test_desire_similarity_duplicate():
    h = MockDesireHost()
    existing = [
        {"content": "我想去吃火锅吧", "satisfied": False},
        {"content": "今天天气真的挺好的", "satisfied": True}
    ]
    
    # Exact match should return True
    assert h._is_desire_similar_to_existing("我想去吃火锅吧", existing) is True
    
    # Highly similar match (Jaccard >= 0.7) should return True
    assert h._is_desire_similar_to_existing("我想去吃火锅", existing) is True

    # Low similarity match should return False
    assert h._is_desire_similar_to_existing("今天好像要下雨了", existing) is False

    # Matching against satisfied desire should return False
    assert h._is_desire_similar_to_existing("今天天气真的挺好的", existing) is False
