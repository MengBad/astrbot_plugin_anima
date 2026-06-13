"""StateSource 协议定义。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StateSource(Protocol):
    """状态源协议接口。"""

    @property
    def name(self) -> str:
        """状态源名称。"""
        ...

    @property
    def scope(self) -> str:
        """状态源作用域：'global' | 'session' | 'runtime'。"""
        ...

    @property
    def format(self) -> str:
        """状态源格式：'json' | 'markdown' | 'jsonl' | 'yaml'。"""
        ...

    @property
    def role(self) -> str:
        """状态源角色：'state' | 'narrative' | 'timeline' | 'personality' | ...。"""
        ...

    async def read(self) -> Any:
        """读取状态数据。"""
        ...

    async def write(self, data: Any) -> None:
        """写入状态数据。"""
        ...

    async def exists(self) -> bool:
        """检查状态源是否存在。"""
        ...

    async def metadata(self) -> dict[str, Any]:
        """获取状态源元数据。"""
        ...
