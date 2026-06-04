"""``southplus`` 包对外稳定接口层。

只 re-export 给 ``core`` / ``main`` / 测试使用的公开符号；实现细节
（具体 HTTP 客户端、抓包常量、解析逻辑）一律保留在 ``southplus`` 包内部
不暴露。改动本文件的导出集合等同于改 API 契约——需要同步评估调用方。

当前公开 API：

* ``SouthPlusEndpoints`` / ``LoginRequest`` / ``LoginResult`` / ``CaptchaPayload``
  ── 数据模型，core 层可以直接持有。
* ``build_endpoints(...)`` ── 端点工厂；core 用它把（可选的）用户配置补齐成完整端点。
* ``SouthPlusSession`` ── 共享 HTTP 会话（持久 ``httpx.Client``），所有 API 的构造入口。
* ``SouthPlusLoginApi`` / ``SouthPlusLoginAttempt`` / ``SouthPlusLoginError``
  ── 登录会话门面与异常。
* ``SouthPlusProfileApi`` / ``SouthPlusProfileError``
  ── 用户资料抓取。
* ``CheckinService`` / ``SouthPlusCheckinError``
  ── 社区签到服务（日签 + 周签）。

包结构：

* ``client.py`` ── ``SouthPlusSession``（共享持久 ``httpx.Client``）
* ``exceptions.py`` ── 所有异常定义
* ``checkin_service.py`` ── ``CheckinService`` 签到服务
* ``models.py`` ── 数据模型与端点工厂
* ``api/`` 子包 ── 各 API 模块
  * ``constants.py`` ── 抓包常量集中定义
  * ``login.py`` ── ``SouthPlusLoginApi`` / ``SouthPlusLoginAttempt``
  * ``profile.py`` ── ``SouthPlusProfileApi`` / ``parse_profile_html``
  * ``daily_checkin.py`` ── ``SouthPlusDailyCheckinApi``
  * ``weekly_checkin.py`` ── ``SouthPlusWeeklyCheckinApi``

抓包流程见 ``docs/southplus-capture.md``（含 Capture 日期约束）。
"""

from ..checkin_service import CheckinService
from ..client import SouthPlusSession
from ..exceptions import (
    SouthPlusCheckinError,
    SouthPlusLoginError,
    SouthPlusProfileError,
)
from .login import SouthPlusLoginApi, SouthPlusLoginAttempt
from .profile import SouthPlusProfileApi
from ..models import (
    CaptchaPayload,
    CheckinReport,
    CheckinStatus,
    CheckinTaskResult,
    LoginRequest,
    LoginResult,
    SouthPlusEndpoints,
    UserProfile,
    build_endpoints,
)

__all__ = [
    # 向后兼容别名
    "CheckinService",
    "SouthPlusCheckinError",
    "SouthPlusLoginApi",
    "SouthPlusLoginAttempt",
    "SouthPlusLoginError",
    "SouthPlusProfileApi",
    "SouthPlusProfileError",
    "SouthPlusSession",
    # 数据模型
    "CaptchaPayload",
    "CheckinReport",
    "CheckinStatus",
    "CheckinTaskResult",
    "LoginRequest",
    "LoginResult",
    "SouthPlusEndpoints",
    "UserProfile",
    "build_endpoints",
]
