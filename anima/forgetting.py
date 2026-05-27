"""自然遗忘：根据时间戳给旧记忆条目加模糊标记。

从 main.py 抽出，无外部依赖，可独立测试。
"""

import re
from datetime import datetime
from typing import Optional


_TIMESTAMP_PATTERN = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')


def apply_forgetting(notes: str, halflife_days: int, now: Optional[datetime] = None) -> str:
    """对超过半衰期的条目做模糊处理。

    - 超过 halflife_days：加 "(记忆模糊)" 后缀
    - 超过 halflife_days * 3：加 "(记忆极度模糊，可能已不准确)" 后缀
    """
    if not notes:
        return notes
    now = now or datetime.now()
    blocks = notes.split("\n---\n")
    processed = []
    for block in blocks:
        match = _TIMESTAMP_PATTERN.search(block)
        if match:
            try:
                entry_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
                age_days = (now - entry_time).days
                if age_days > halflife_days * 3:
                    block = block.rstrip() + " (记忆极度模糊，可能已不准确)"
                elif age_days > halflife_days:
                    block = block.rstrip() + " (记忆模糊)"
            except (ValueError, TypeError):
                pass
        processed.append(block)
    return "\n---\n".join(processed)
