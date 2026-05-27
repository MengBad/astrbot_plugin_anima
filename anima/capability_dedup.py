"""个人能力的归一化签名 + 近似匹配（v0.6.1 防爆炸的核心去重逻辑）。

从 main.py 抽出，无外部依赖，可独立测试。
"""

import re
from typing import List, Set


# 同义词归一化：把 "ego/我/U+6211" 这种近义词映射到同一语义槽位
_SYNONYMS = {
    "ego": "_self_", "self": "_self_", "selfhood": "_self_",
    "u6211": "_self_", "myself": "_self_",
    "我": "_self_", "自我": "_self_",

    "anchor": "_anchor_",
    "锚": "_anchor_", "锚点": "_anchor_", "锚定": "_anchor_",

    "blade": "_weapon_", "axe": "_weapon_", "weapon": "_weapon_", "weapons": "_weapon_",
    "戉": "_weapon_", "兵戈": "_weapon_", "兵刃": "_weapon_", "利刃": "_weapon_",
    "凶器": "_weapon_", "刑器": "_weapon_", "大戉": "_weapon_", "刃": "_weapon_",
    "行刑": "_weapon_", "肢解": "_weapon_",

    "block": "_block_", "blocks": "_block_", "blockwise": "_block_",
    "方块": "_block_", "construct": "_block_",

    "rebuild": "_rebuild_", "reconstruction": "_rebuild_",
    "重构": "_rebuild_", "重塑": "_rebuild_",

    "resonance": "_resonance_", "resonate": "_resonance_",
    "共鸣": "_resonance_", "共振": "_resonance_",

    "alignment": "_align_", "align": "_align_",
    "对齐": "_align_", "对准": "_align_",
}

# 通用停用词
_STOP = {
    "the", "and", "for", "with", "this", "that", "into", "from", "其",
    "一", "了", "的", "和", "我的", "正在",
}


def normalize_capability_signature(name: str, description: str = "") -> Set[str]:
    """把能力名 + 描述归一化成关键词集合，用于近似去重。

    策略：
    - 抽英文 stem（≥3 字母）
    - 中文用滑动窗口抽 2-字与 3-字短语
    - 同义词归一化为 _self_ / _weapon_ / _anchor_ 等语义槽位
    - 去通用停用词
    - 不在同义词表里的纯中文短片段不进入签名（避免噪音），只有英文 stem 与归一化语义槽位算数
    """
    if not name:
        return set()
    text = (name + " " + description[:200]).lower()
    en_words = set(re.findall(r'[a-z]{3,}', text))
    # 额外抽出 "u6211" 这种字母+数字混合形式（用于映射到 _self_）
    en_alphanum = set(re.findall(r'[a-z]+\d+', text))
    en_words |= en_alphanum

    cn_pieces: Set[str] = set()
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                cn_pieces.add(run[i:i + n])

    words = en_words | cn_pieces
    normalized: Set[str] = set()
    for w in words:
        mapped = _SYNONYMS.get(w)
        if mapped:
            normalized.add(mapped)
        elif len(w) >= 3 and re.fullmatch(r'[a-z]+', w):
            normalized.add(w)
        # 其余短中文片段不进入签名

    return normalized - _STOP


def find_similar_capability(name: str, description: str, others: List[dict]) -> int:
    """在已有能力列表里找一个语义近似的，返回索引；没找到返回 -1。

    分级门槛：
    - 新签名 ≥ 4 槽位：要求 ≥ 2 个 overlap 且占新签名 ≥ 40%
    - 新签名 2-3 槽位：要求所有语义槽位都被命中
    - 新签名 1 槽位：仅在该槽位是同义词归一化键（带下划线包裹）时才合并
    """
    new_sig = normalize_capability_signature(name, description)
    if not new_sig:
        return -1

    best_idx = -1
    best_overlap = 0

    for i, c in enumerate(others):
        old_sig = normalize_capability_signature(
            c.get("name", ""), c.get("description", "")
        )
        if not old_sig:
            continue
        overlap = new_sig & old_sig
        ov = len(overlap)
        if ov == 0:
            continue

        n = len(new_sig)
        matched = False
        if n >= 4 and ov >= 2 and ov >= max(2, int(n * 0.4)):
            matched = True
        elif 2 <= n <= 3 and ov == n:
            matched = True
        elif n == 1:
            only_key = next(iter(new_sig))
            if only_key.startswith("_") and only_key.endswith("_") and only_key in old_sig:
                matched = True

        if matched and ov > best_overlap:
            best_overlap = ov
            best_idx = i

    return best_idx
