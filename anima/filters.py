"""内容过滤纯函数：拒绝语检测 / 敏感词检测。

从 main.py 抽出，无外部依赖，可独立测试。
"""

import re
from typing import Iterable, Optional


DEFAULT_REJECT_PHRASES = [
    # 英文经典拒答
    "I can't discuss",
    "I cannot",
    "I'm not able",
    "I don't think I should",
    "I won't be able",
    "I'm unable to",
    # 中文经典拒答
    "我无法",
    "我不能",
    "我没办法",
    # v0.8.2: Claude/Gemini 中文委婉拒答模板（生产观察）
    "对此我无法",
    "对此，我无法",
    "无法被讨论",
    "无法展开讨论",
    "无法进行讨论",
    "无法再用言语",
    "无需再用言语",
    "无需再做进一步",
    "更倾向于保持顺其自然",
    "目前已无需",
    "让它静静地安放",
    "这条记忆的内容",
    "这段记忆的具体内容",
]


def is_rejected(text: str, reject_phrases: Optional[Iterable[str]] = None) -> bool:
    """检查文本是否包含拒绝短语。"""
    if not text:
        return False
    phrases = list(reject_phrases) if reject_phrases else DEFAULT_REJECT_PHRASES
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in phrases)


# 中文敏感关键词（子串匹配）
_CN_SENSITIVE = ('密钥', '秘钥', '口令', '凭证')

# 英文敏感关键词（单词边界匹配，不区分大小写）
_EN_SENSITIVE_PATTERN = re.compile(
    r'\b(?:'
    r'key|token|password|passwd|secret|api_key|apikey|access_key|'
    r'private_key|authorization|bearer|credential|credentials|auth'
    r')\b',
    re.IGNORECASE,
)

# 高熵字符串模式（连续 30+ 字母数字）
_ENTROPY_PATTERN = re.compile(r'[A-Za-z0-9]{30,}')


def is_sensitive(text: str) -> bool:
    """检查文本是否包含敏感内容（密钥、token、高熵字符串等）。

    - 中文敏感词使用子串匹配
    - 英文敏感词使用单词边界（不会误伤 author/keyboard/secretary 等正常单词）
    - 检测连续 30+ 字符的字母数字混合串（潜在密钥/token）
    """
    if not text:
        return False
    if any(kw in text for kw in _CN_SENSITIVE):
        return True
    if _EN_SENSITIVE_PATTERN.search(text):
        return True
    match = _ENTROPY_PATTERN.search(text)
    if match:
        seg = match.group()
        has_upper = any(c.isupper() for c in seg)
        has_lower = any(c.islower() for c in seg)
        has_digit = any(c.isdigit() for c in seg)
        if sum([has_upper, has_lower, has_digit]) >= 2:
            return True
    return False
