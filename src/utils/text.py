"""字符串工具：脱敏与 token 生成。"""

from __future__ import annotations

import secrets


def mask_secret(value: str, *, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]}"


def generate_token() -> str:
    # 32 字节 URL-safe token：抵抗猜测；链接只在 TTL 窗口内有效。
    return secrets.token_urlsafe(32)
