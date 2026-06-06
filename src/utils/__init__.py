"""无状态工具函数集合。

按职责拆分为多个子模块，``__init__`` 集中 re-export，方便下游统一通过
``from src.utils import ...`` 引用。子模块边界：

* ``crypto``：cookie / 凭据加解密原语。
* ``text``：脱敏、token 生成等字符串工具。
* ``timeutil``：时间戳、ISO 时间。
* ``url``：URL 拼接、cookie 域解析。
* ``events``：AstrBot 事件平台名归一化。
* ``messages``：聊天侧展示文案。
* ``season``：季节名判断。
"""

from .crypto import decrypt_secret, encrypt_secret
from .events import get_event_platform, is_aiocqhttp_event
from .logger import get_plugin_logger, plugin_logger
from .messages import format_add_account_result, format_checkin_response
from .season import season_name
from .text import generate_token, mask_secret
from .timeutil import (
    current_iso_week,
    current_iso_week_label,
    current_local_date,
    expires_at_after,
    now_iso,
)
from .url import (
    derive_cookie_domains_from_url,
    derive_default_endpoint,
    join_url,
    parse_cookie_domains,
    wrap_docs_link,
)

__all__ = [
    "current_iso_week",
    "current_iso_week_label",
    "current_local_date",
    "decrypt_secret",
    "derive_cookie_domains_from_url",
    "derive_default_endpoint",
    "encrypt_secret",
    "expires_at_after",
    "format_add_account_result",
    "format_checkin_response",
    "generate_token",
    "get_event_platform",
    "get_plugin_logger",
    "is_aiocqhttp_event",
    "join_url",
    "mask_secret",
    "now_iso",
    "parse_cookie_domains",
    "plugin_logger",
    "season_name",
    "wrap_docs_link",
]
