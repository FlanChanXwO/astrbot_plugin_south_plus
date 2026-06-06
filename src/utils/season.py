"""季节名 helper。"""

from __future__ import annotations

import datetime


def season_name(now: datetime.datetime | None = None) -> str:
    """返回当前季节的英文名，用于页面主题和用户卡片渲染。"""
    if now is None:
        now = datetime.datetime.now()
    month = now.month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"
