"""South Plus 抓包得到的接口入参/出参/端点数据模型与工厂。

抓包来的常量（默认 URL、UA、表单字段默认值等）见 ``constants`` 子模块。
本模块只保留数据模型与基于常量的工厂函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..utils import derive_cookie_domains_from_url, join_url
from .constants import (
    DEFAULT_CAPTCHA_PATH,
    DEFAULT_COOKIE_TTL,
    DEFAULT_HIDE_ID,
    DEFAULT_LOGIN_PATH,
    DEFAULT_LOGIN_TYPE,
    DEFAULT_SITE_BASE_URL,
    DEFAULT_USER_AGENT,
    DEFAULT_VERIFY_PATH,
)


@dataclass(slots=True)
class SouthPlusEndpoints:
    """South Plus 站点的 URL 和 cookie 域。

    所有 URL 必须是绝对地址。``cookie_domains`` 用于持久化时过滤外站
    cookie（例如 Cloudflare 自己的 cookie 不应该写到我们的数据库里）。
    """

    site_base_url: str
    login_url: str
    captcha_url: str
    verify_url: str
    cookie_domains: tuple[str, ...]
    user_agent: str


@dataclass(slots=True)
class LoginRequest:
    """提交到 South Plus 登录接口的字段。

    与 phpwind 登录表单字段一一对应：

    * ``username`` -> 表单 ``pwuser``
    * ``password`` -> 表单 ``pwpwd``
    * ``captcha``  -> 表单 ``gdcode``
    * ``login_type`` -> 表单 ``lgt``
    * ``hide_id``    -> 表单 ``hideid``
    * ``cookie_ttl`` -> 表单 ``cktime``
    """

    username: str
    password: str
    captcha: str
    login_type: str = DEFAULT_LOGIN_TYPE
    hide_id: str = DEFAULT_HIDE_ID
    cookie_ttl: str = DEFAULT_COOKIE_TTL


@dataclass(slots=True)
class LoginResult:
    """登录成功后从 South Plus 收集到的可持久化结果。"""

    username: str
    cookie: str
    message: str


@dataclass(slots=True)
class CaptchaPayload:
    """South Plus 验证码图片字节及其 Content-Type。"""

    content_type: str
    body: bytes


class CheckinStatus(str, Enum):
    """单项签到（日/周）的执行结果。"""

    SUCCESS = "success"  # 本次跑通了 apply + collect，从站点拿到了奖励文案
    ALREADY_DONE = "already_done"  # 站点告知今日/本周已完成（视作成功）
    FAILED = "failed"  # 任何步骤抛错；详细错误见 ``error`` 字段


@dataclass(slots=True)
class CheckinTaskResult:
    """日签或周签的单次结果。

    * ``status`` ── 见 ``CheckinStatus``。
    * ``message`` ── 给用户看的可读结果文案（来自站点 XML 的 message 段）。
    * ``error`` ── 站点原始错误内容；用于落库以便排查，不直接展示给用户。
    """

    status: CheckinStatus
    message: str = ""
    error: str = ""


@dataclass(slots=True)
class CheckinReport:
    """一次 ``/spcheckin`` 调用的完整结果。"""

    daily: CheckinTaskResult
    weekly: CheckinTaskResult


@dataclass(slots=True)
class UserProfile:
    """South Plus 用户资料抓取结果。

    字段来源于 ``profile.php`` 抓包截图——见 docs/southplus-capture.md。
    解析失败的字段会以合理默认值返回（空串 / 0），不会为 None。
    """

    username: str = ""
    uid: str = ""
    signature: str = ""
    avatar_url: str = ""
    title: str = ""
    essence: int = 0
    posts: int = 0
    hp: int = 0
    soul: int = 0
    sp_coin: str = ""
    lp: int = 0
    online_hours: str = ""
    register_date: str = ""
    last_login_date: str = ""


def build_endpoints(
    *,
    site_base_url: str = "",
    login_url: str = "",
    captcha_url: str = "",
    verify_url: str = "",
    cookie_domains: tuple[str, ...] = (),
    user_agent: str = "",
) -> SouthPlusEndpoints:
    """按抓包默认值填补缺失字段，构造 ``SouthPlusEndpoints``。

    任一字段传空字符串/空元组时回落到 ``constants`` 中的 ``DEFAULT_*``。
    改默认值时改 ``constants.py`` 即可，调用方（``config_manager`` 等）
    不需要感知抓包细节。
    """

    base = (site_base_url or DEFAULT_SITE_BASE_URL).rstrip("/")
    return SouthPlusEndpoints(
        site_base_url=base,
        login_url=login_url or join_url(base, DEFAULT_LOGIN_PATH),
        captcha_url=captcha_url or join_url(base, DEFAULT_CAPTCHA_PATH),
        verify_url=verify_url or join_url(base, DEFAULT_VERIFY_PATH),
        cookie_domains=cookie_domains or derive_cookie_domains_from_url(base),
        user_agent=user_agent or DEFAULT_USER_AGENT,
    )
