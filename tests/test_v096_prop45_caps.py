"""v0.9.6 Property 4/5: 矛盾去重+上限、工具记录上限不变量。

矛盾去重逻辑内嵌在异步 _maybe_detect_contradiction 中，难以纯逻辑单测；这里直接验证
text_similarity 去重判定 + 上限裁剪的不变量（与实现使用的同一函数），以及工具记录裁剪。
"""
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

from hypothesis import given, settings, strategies as st  # noqa: E402
from anima.capability_dedup import text_similarity  # noqa: E402


def _dedup_and_cap(existing_descs, new_desc, threshold, cap):
    """复刻 rumination.py 矛盾去重+上限逻辑。"""
    if any(text_similarity(new_desc, d) >= threshold for d in existing_descs[-10:]):
        return existing_descs  # 重复，不写
    out = existing_descs + [new_desc]
    return out[-cap:]


# Feature: v096-hygiene-performance, Property 4: 矛盾去重 + 上限不变量 ——
# 相似矛盾不重复记录，且长度始终 <= cap。
@settings(max_examples=100)
@given(
    seq=st.lists(st.text(min_size=3, max_size=20), min_size=0, max_size=30),
    cap=st.integers(min_value=1, max_value=10),
)
def test_prop4_contradiction_dedup_cap(seq, cap):
    threshold = 0.7
    acc = []
    for desc in seq:
        acc = _dedup_and_cap(acc, desc, threshold, cap)
        # 上限不变量
        assert len(acc) <= cap

    # 去重不变量：相同描述加两次不增长
    base = _dedup_and_cap([], "一条很独特的矛盾描述内容", threshold, cap)
    after = _dedup_and_cap(base, "一条很独特的矛盾描述内容", threshold, cap)
    assert len(after) == len(base)


def _tool_records_cap(records, rmax):
    """复刻 capabilities.py 工具记录裁剪。"""
    if len(records) > rmax:
        return records[-rmax:]
    return records


# Feature: v096-hygiene-performance, Property 5: 工具记录上限不变量 ——
# 追加后长度 <= rmax，且保留最近记录。
@settings(max_examples=100)
@given(
    n=st.integers(min_value=0, max_value=500),
    rmax=st.integers(min_value=1, max_value=200),
)
def test_prop5_tool_records_cap(n, rmax):
    records = list(range(n))  # 用序号标识"最近"
    records.append(n)  # 模拟 append 一条
    capped = _tool_records_cap(records, rmax)
    assert len(capped) <= rmax
    # 保留的是最近的（末尾元素一定在）
    assert capped[-1] == n
