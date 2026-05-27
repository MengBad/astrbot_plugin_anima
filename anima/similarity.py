"""文本相似度工具：ngram tokenize + Jaccard + Cosine。

从 main.py 抽出，无外部依赖，可独立测试。
"""

import math
import re
from typing import List, Set


def text_token_set(text: str) -> Set[str]:
    """抽出文本的 token 集合（中文 ngram + 英文 stem）。

    - 英文：长度 ≥ 3 的字母词
    - 中文：滑动窗口抽 2 字与 3 字短语
    """
    if not text:
        return set()
    text_lower = text.lower()
    en = set(re.findall(r'[a-z]{3,}', text_lower))
    cn_runs = re.findall(r'[\u4e00-\u9fff]+', text_lower)
    cn_pieces: Set[str] = set()
    for run in cn_runs:
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                cn_pieces.add(run[i:i + n])
    return en | cn_pieces


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Jaccard 相似度：|A ∩ B| / |A ∪ B|"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """两个等长向量的余弦相似度。零向量或长度不等返回 0。"""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def text_jaccard(a: str, b: str) -> float:
    """两段文本的 ngram + Jaccard 相似度，便捷封装。"""
    return jaccard_similarity(text_token_set(a), text_token_set(b))
