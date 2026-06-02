"""URL 与 cookie 域解析工具。"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def join_url(base: str, path: str) -> str:
    # 把 path 拼到 base 末尾，规避双斜杠和漏斜杠。
    base = (base or "").rstrip("/")
    path = (path or "").lstrip("/")
    if not base:
        return path
    if not path:
        return base
    return f"{base}/{path}"


def derive_default_endpoint(base: str, path: str) -> str:
    return join_url(base, path)


_DOMAIN_SPLIT = re.compile(r"[\s,]+")


def parse_cookie_domains(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    parts = [item.strip().lower() for item in _DOMAIN_SPLIT.split(raw) if item.strip()]
    return tuple(dict.fromkeys(parts))


def derive_cookie_domains_from_url(url: str) -> tuple[str, ...]:
    host = urlparse(url).hostname or ""
    if not host:
        return ()
    host = host.lower()
    parts = host.split(".")
    if len(parts) >= 2:
        registrable = ".".join(parts[-2:])
        if registrable != host:
            return (host, registrable)
    return (host,)
