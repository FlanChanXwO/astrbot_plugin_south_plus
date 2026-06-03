"""时间相关无状态工具。"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def expires_at_after(ttl_seconds: int) -> float:
    return time.time() + ttl_seconds


# 南+ 是中国站点，签到边界按 UTC+8 自然日 / 自然周划分。
_CST = timezone(timedelta(hours=8))


def current_local_date() -> str:
    """返回 ``YYYY-MM-DD``（UTC+8）。签到的"今天"以此为准。"""

    return datetime.now(_CST).strftime("%Y-%m-%d")


def current_iso_week() -> str:
    """返回 ``YYYY-Www``（UTC+8 视角下的 ISO 周）。签到的"本周"以此为准。

    ISO 周从周一起，与南+ 网站的周签节奏一致——周一签到完计入新一周。
    """

    now = datetime.now(_CST)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"
