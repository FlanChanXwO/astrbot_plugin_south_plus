"""Plugin Pages Web API 注册入口。"""

from __future__ import annotations

from typing import Any

from .handlers import SouthPlusPageApi


def register_page_apis(context: Any, **deps: Any) -> SouthPlusPageApi:
    """注册 South Plus Dashboard 所需 Web API，并返回 handler 实例。"""
    api = SouthPlusPageApi(**deps)
    api.register(context)
    return api


__all__ = ["SouthPlusPageApi", "register_page_apis"]
