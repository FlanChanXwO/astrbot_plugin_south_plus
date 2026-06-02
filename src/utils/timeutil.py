"""时间相关无状态工具。"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def expires_at_after(ttl_seconds: int) -> float:
    return time.time() + ttl_seconds
