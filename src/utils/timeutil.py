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
    这串只用作 ``checkin_record`` 的 cache key——稳定、整周不变；不直接给
    用户看。给用户的友好标签用 :func:`current_iso_week_label`。
    """

    now = datetime.now(_CST)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def current_iso_week_label() -> str:
    """返回本周 Mon-Sun 的日期区间字符串，例如 ``2026-06-01~06-07``。

    给用户看的友好周签标签——避免 ``2026-W23`` 这种 ISO 周编号直接抛给
    非技术用户造成困惑。
    """

    now = datetime.now(_CST)
    weekday = now.isoweekday()  # 1=Mon ... 7=Sun
    monday = now - timedelta(days=weekday - 1)
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%Y-%m-%d')}~{sunday.strftime('%m-%d')}"
