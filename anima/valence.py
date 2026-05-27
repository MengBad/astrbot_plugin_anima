"""记忆情感效价估算（Phase 3B 记忆情绪染色）。

从 main.py 抽出，无外部依赖，可独立测试。
"""

from typing import List


_WARM_KEYWORDS = (
    "开心", "温暖", "谢谢", "喜欢", "爱", "幸福", "笑", "好",
    "甜", "抱", "永远", "珍惜", "感动",
)

_CONFLICT_KEYWORDS = (
    "伤心", "难过", "离开", "讨厌", "滚", "吵", "骗", "哭",
    "恨", "再见", "不要我", "失望", "背叛", "冷",
)


def estimate_memory_valence(text: str) -> float:
    """估算文本的情感效价。

    - 正值（≤ 0.5）：温暖回忆
    - 负值（≥ -0.5）：冲突回忆
    - 0：中性
    """
    if not text:
        return 0.0
    t = text.lower()
    w = sum(1 for k in _WARM_KEYWORDS if k in t)
    c = sum(1 for k in _CONFLICT_KEYWORDS if k in t)
    valence = (w - c) * 0.08
    return max(-0.5, min(0.5, valence))


def rerank_memories_by_emotion(memories: List[str], current_emotion: float) -> List[str]:
    """根据当前情绪对记忆重排序。

    - 高情绪（> 0.55）：温暖记忆优先
    - 低情绪：冲突记忆优先
    """
    if not memories or len(memories) <= 1:
        return list(memories)
    scored = [(m, estimate_memory_valence(m)) for m in memories]
    reverse_sort = current_emotion > 0.55
    scored.sort(key=lambda x: x[1], reverse=reverse_sort)
    return [m for m, _ in scored]
