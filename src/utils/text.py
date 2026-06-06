"""字符串工具：脱敏与 token 生成。"""

from __future__ import annotations

import secrets
import string


_LOGIN_TOKEN_ALPHABET = string.ascii_letters + string.digits


def mask_secret(value: str, *, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]}"


def generate_token() -> str:
    # 用户要求登录链接中的随机串固定为 6 个字符，缩短 URL 展示长度。
    return "".join(secrets.choice(_LOGIN_TOKEN_ALPHABET) for _ in range(6))
