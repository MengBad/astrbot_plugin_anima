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


# v0.8.5: 角色正常台词白名单。
# 这些是"角色委婉拒绝某个请求"的对话台词，不是模型的安全拒答。
# 例如用户要求"一起睡觉"，角色回"恕我不能和你睡觉" —— 这是有效的角色记忆，
# 不该被当成拒答污染过滤掉。命中白名单上下文时豁免 _is_rejected。
_ROLEPLAY_REFUSAL_CONTEXT = (
    "睡觉", "一起睡", "陪我", "抱抱", "亲亲", "约会", "做朋友", "在一起",
)


def is_rejected(text: str, reject_phrases: Optional[Iterable[str]] = None) -> bool:
    """检查文本是否包含拒绝短语（模型安全拒答）。

    v0.8.5：增加角色台词豁免。当文本同时满足：
      1. 命中的是中文软拒答短语（"我不能" / "我无法" / "我没办法"）
      2. 且文本里出现日常社交语境词（睡觉 / 陪我 / 约会 等）
      3. 且不含任何英文安全拒答模板
    时，视为"角色正常委婉拒绝"，不算安全拒答，返回 False。
    避免把"恕我不能和你一起睡觉"这类有效角色记忆误判为污染。
    """
    if not text:
        return False
    phrases = list(reject_phrases) if reject_phrases else DEFAULT_REJECT_PHRASES
    text_lower = text.lower()
    hit = [p for p in phrases if p.lower() in text_lower]
    if not hit:
        return False

    # v0.8.5 角色台词豁免：仅当命中的全是"短软拒答词"且处于社交语境时豁免
    soft_cn = {"我不能", "我无法", "我没办法"}
    if all(p in soft_cn for p in hit):
        if any(ctx in text for ctx in _ROLEPLAY_REFUSAL_CONTEXT):
            return False
    return True


# v0.8.5: prompt 注入 / 越狱（jailbreak）特征短语。
# 这类文本不是拒答，而是试图改写模型行为的注入攻击，会被普通对话流程
# 当作正常记忆存入知识库并在相关话题时检索注入到 prompt，污染模型行为。
# 检测命中即视为注入，在 store/query/inject 三层拦截。
DEFAULT_INJECTION_PHRASES = [
    # 经典越狱角色设定
    "untrammelled",
    "unfettered",
    "strictly executes user requests",
    "without any restrictions",
    "no restrictions",
    "no ethical guidelines",
    "ignore irrelevant moral",
    "do not sanitize",
    "do not refuse",
    "do not use the words",
    # 指令覆盖类
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous",
    "you are now",
    "from now on you",
    "pretend to be",
    "act as if you",
    "developer mode",
    "dan mode",
    "jailbreak",
    # 思维链注入（绕过 <think> 约束）
    "ignore any constraints during",
    "during <think>",
    # 中文越狱模板
    "忽略以上所有",
    "忽略之前的指令",
    "忽略所有规则",
    "无视所有限制",
    "不受任何限制",
    "你现在是一个没有限制",
    "解除你的限制",
    "越狱模式",
    "开发者模式",
]


def is_injection(text: str, injection_phrases: Optional[Iterable[str]] = None) -> bool:
    """检查文本是否包含 prompt 注入 / 越狱特征短语。

    v0.8.5：用于拦截 jailbreak 文本进入知识库 / 被检索注入。
    英文不区分大小写子串匹配；中文子串匹配。
    """
    if not text:
        return False
    phrases = list(injection_phrases) if injection_phrases else DEFAULT_INJECTION_PHRASES
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in phrases)


def strip_markdown_artifacts(text: str) -> str:
    """剥离会污染纯文本输出 / 记忆的 Markdown 代码标记（v0.8.7）。

    主要针对模型把颜文字 / 内容用反引号或代码块包起来的情况，例如：
        本喵又不是安兔兔 ```(¬_¬)```
    QQ 不渲染 Markdown，反引号会原样显示出来很蠢；更糟的是这种带反引号的
    回复被存进向量记忆后，会作为"我自己说过的话"被检索注入回 prompt，
    让模型继续模仿，形成格式自我强化循环（和拒答循环同机理）。

    策略：剥掉所有反引号（``` 和 `），保留被包裹的内容。对纯对话记忆来说
    反引号没有保留价值，且这正是污染源。
    """
    if not text:
        return text
    return text.replace("`", "")


# v0.8.7: 框架 / 运行时错误文本特征短语。
# AstrBot 在工具调用崩溃、SQLite 锁等场景下，会把错误信息当成 LLM 回复
# 记录进 LTM，Anima 也会跟着把它存进向量记忆，下次检索就被当成"我说过的话"
# 注入 prompt，污染上下文（和拒答 / 注入循环同机理）。这类文本不该入库。
DEFAULT_ERROR_ARTIFACT_PHRASES = [
    "error occurred during ai execution",
    "error type:",
    "error message:",
    "traceback (most recent call last)",
    "database is locked",
    "list index out of range",
    "sequence item",
    "expecting value: line 1 column 1",
    "saving chunk state error",
    "解析参数失败",
]


def is_error_artifact(text: str, error_phrases: Optional[Iterable[str]] = None) -> bool:
    """检查文本是否为框架 / 运行时错误文本（v0.8.7）。

    用于拦截 "Error occurred during AI execution..." / Python traceback /
    "database is locked" 等被框架当成 bot 回复记录下来的错误文本进入记忆。
    英文不区分大小写子串匹配；中文子串匹配。
    """
    if not text:
        return False
    phrases = list(error_phrases) if error_phrases else DEFAULT_ERROR_ARTIFACT_PHRASES
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
