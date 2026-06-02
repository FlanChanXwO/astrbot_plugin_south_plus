"""South Plus 站点逆向接口与数据模型。

本包内的所有内容都来自对 South Plus 站点的抓包结果。South Plus 改版时
请同步本包以及 ``docs/southplus-capture.md``（含 Capture 日期）。
"""

from . import constants
from .client import SouthPlusClient, SouthPlusLoginAttempt, SouthPlusLoginError
from .models import (
    CaptchaPayload,
    LoginRequest,
    LoginResult,
    SouthPlusEndpoints,
    build_endpoints,
)

__all__ = [
    "CaptchaPayload",
    "LoginRequest",
    "LoginResult",
    "SouthPlusClient",
    "SouthPlusEndpoints",
    "SouthPlusLoginAttempt",
    "SouthPlusLoginError",
    "build_endpoints",
    "constants",
]
