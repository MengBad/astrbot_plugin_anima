"""StateStore 统一状态存储抽象层。

提供统一的状态存储接口，支持 snapshot/diff/rollback 语义，
将所有持久化路径收敛到一致的抽象层。
"""

from .base import StateSource
from .json_source import JsonStateSource
from .markdown_source import MarkdownStateSource
from .jsonl_source import JsonlStateSource
from .snapshot import Snapshot, Diff, Change
from .store import StateStore
from .write_mixin import StateStoreWriteMixin

__all__ = [
    "StateSource",
    "JsonStateSource",
    "MarkdownStateSource",
    "JsonlStateSource",
    "Snapshot",
    "Diff",
    "Change",
    "StateStore",
    "StateStoreWriteMixin",
]
