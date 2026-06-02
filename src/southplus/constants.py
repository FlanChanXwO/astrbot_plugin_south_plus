"""South Plus 抓包得到的常量。

本文件是抓包结论的唯一权威。改动须同步 ``docs/southplus-capture.md`` 顶部
的 ``Capture 日期`` 与"当前抓包结果"小节。

放置原则：

* **抓包来的事实**（URL 路径、表单字段默认值、cookie 名后缀、失败关键字、
  浏览器 UA 等）放在本文件。
* **项目级且与站点无关的常量**（``PLUGIN_NAME``、日志前缀等）放在
  ``src/shared/constants.py``。
"""

from __future__ import annotations

# 站点主域：见 docs/southplus-capture.md 的"当前抓包结果 → 端点"。镜像如
# bbs.south-plus.org 字段集一致但 cookie 前缀 hash 不同。
DEFAULT_SITE_BASE_URL = "https://www.south-plus.net"

# phpwind 登录三件套路径。
DEFAULT_LOGIN_PATH = "login.php"
DEFAULT_CAPTCHA_PATH = "ck.php"
DEFAULT_VERIFY_PATH = "index.php"

# phpwind 登录表单 hidden 字段默认值（抓包步骤 2）。
DEFAULT_FORM_FORWARD = ""
DEFAULT_FORM_STEP = "2"
DEFAULT_FORM_SUBMIT = "登 录"

# 登录表单 user-selectable 默认值。
DEFAULT_LOGIN_TYPE = "0"  # 0=用户名 / 1=UID / 2=Email
DEFAULT_HIDE_ID = "0"  # 0=显示在线 / 1=隐身登录
DEFAULT_COOKIE_TTL = "31536000"  # 一年；可选 31536000/2592000/86400/3600/0

# 用于通过 Cloudflare 的浏览器风格 UA。改 UA 时建议先在
# docs/southplus-capture.md 步骤 1 复测一次连通性。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# 站点登录成功的 cookie 名后缀（phpwind 通用，前缀是站点 hash）。
LOGIN_COOKIE_NAME_SUFFIXES = ("_winduser", "_winduid")

# 失败页面中的中文关键字 -> 面向用户的错误信息。顺序即优先级；先匹配
# 验证码错误以引导用户重填验证码。
FAILURE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("认证码", "验证码错误或站点要求验证码，请刷新验证码后重试。"),
    ("验证码", "验证码错误或站点要求验证码，请刷新验证码后重试。"),
    ("密码错误", "账号或密码错误。"),
    ("密码不正确", "账号或密码错误。"),
    ("用户名不存在", "账号不存在。"),
    ("账号被锁定", "账号被站点锁定。"),
    ("登录次数", "登录失败次数过多，请稍后再试。"),
)
