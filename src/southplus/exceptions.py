"""South Plus 异常定义。

所有面向调用方可展示的异常统一放这里，不分散在各 API 模块中。
"""

from __future__ import annotations

__all__ = [
    "SouthPlusCheckinError",
    "SouthPlusLoginError",
    "SouthPlusProfileError",
]


class SouthPlusLoginError(RuntimeError):
    """South Plus 登录流程中产生的可向用户展示的错误。"""


class SouthPlusProfileError(RuntimeError):
    """profile.php 抓取或解析失败。可向用户展示。"""


class SouthPlusCheckinError(RuntimeError):
    """签到流程在客户端层抛出的错误，可向用户展示。"""
