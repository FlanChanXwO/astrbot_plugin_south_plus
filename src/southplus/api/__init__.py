"""``southplus`` 包对外稳定接口层。

只 re-export 给 ``core`` / ``main`` / 测试使用的公开符号；实现细节
（具体 HTTP 客户端、抓包常量、解析逻辑）一律保留在 ``southplus`` 包内部
不暴露。改动本文件的导出集合等同于改 API 契约——需要同步评估调用方。

当前公开 API：

* ``SouthPlusEndpoints`` / ``LoginRequest`` / ``LoginResult`` / ``CaptchaPayload``
  ── 数据模型，core 层可以直接持有。
* ``build_endpoints(...)`` ── 端点工厂；core 用它把（可选的）用户配置补齐成完整端点。
* ``SouthPlusClient`` / ``SouthPlusLoginAttempt`` / ``SouthPlusLoginError``
  ── 登录会话门面与异常。
"""

from ..client import SouthPlusClient, SouthPlusLoginAttempt, SouthPlusLoginError
from ..models import (
    CaptchaPayload,
    LoginRequest,
    LoginResult,
    SouthPlusEndpoints,
    UserProfile,
    build_endpoints,
)
from ..profile_client import SouthPlusProfileClient, SouthPlusProfileError

__all__ = [
    "CaptchaPayload",
    "LoginRequest",
    "LoginResult",
    "SouthPlusClient",
    "SouthPlusEndpoints",
    "SouthPlusLoginAttempt",
    "SouthPlusLoginError",
    "SouthPlusProfileClient",
    "SouthPlusProfileError",
    "UserProfile",
    "build_endpoints",
]
