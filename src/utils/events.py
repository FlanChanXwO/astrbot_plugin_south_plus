"""AstrBot 事件相关的无状态 helper。"""

from __future__ import annotations

from typing import Protocol


class _PlatformEvent(Protocol):
    """只描述本模块需要的事件能力，避免 utils 直接依赖 AstrBot 类型。"""

    def get_platform_name(self) -> str | None: ...


def get_event_platform(event: _PlatformEvent) -> str:
    """返回事件平台名；AstrBot 返回空值时统一归一为空字符串。"""
    return (event.get_platform_name() or "").strip()


def is_aiocqhttp_event(event: _PlatformEvent) -> bool:
    """是否为 aiocqhttp（OneBot v11）平台。"""
    return "aiocqhttp" in get_event_platform(event)
