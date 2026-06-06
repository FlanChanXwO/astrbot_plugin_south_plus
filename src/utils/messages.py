"""聊天侧展示文案 helper。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.datamodels import AddAccountResult
    from ..southplus.api import CheckinTaskResult, UserProfile


def format_add_account_result(
    result: "AddAccountResult",
    profile: "UserProfile",
    *,
    auto_checkin_hint: bool = False,
) -> str:
    """格式化登录绑定结果。"""
    username = profile.username or "(未记录)"
    uid = profile.uid or result.account.sp_uid or "(未知)"
    if result.status == "created":
        text = f"登录成功：用户名：{username}，id：{uid}"
        if auto_checkin_hint:
            text += "\n已在后台开启自动社区签到（可用 /spautocheckin 切换当前账号签到）"
        return text
    if result.status == "refreshed":
        return (
            f"登录成功（该 UID 已绑定过，已刷新 Cookie 并切换为当前账号）：\n"
            f"用户名：{username}，id：{uid}"
        )
    return (
        f"该 UID（{uid}）已被其他用户绑定，无法绑定。\n"
        "如确需迁移，请联系管理员从数据库删除该 UID 的旧绑定后再试。"
    )


def format_checkin_response(
    *,
    uid: str,
    today: str,
    this_week_label: str,
    fresh_daily: "CheckinTaskResult | None",
    fresh_weekly: "CheckinTaskResult | None",
) -> str:
    """格式化一次日签 + 周签的用户可见结果。"""
    daily_line = _format_dimension_line(
        label="日签",
        period_key=today,
        fresh=fresh_daily,
    )
    weekly_line = _format_dimension_line(
        label="周签",
        period_key=this_week_label,
        fresh=fresh_weekly,
    )
    return f"South Plus 签到结果\nUID: {uid}\n{daily_line}\n{weekly_line}"


def _format_dimension_line(
    *,
    label: str,
    period_key: str,
    fresh: "CheckinTaskResult | None",
) -> str:
    if fresh is None:
        return f"{label}（{period_key}，缓存）: 已签到"
    if fresh.status == "success":
        return f"{label}（{period_key}，新签）: 成功，{fresh.message}"
    if fresh.status == "already_done":
        return f"{label}（{period_key}，新签）: 已签到，{fresh.message}"
    detail = fresh.message or fresh.error or "未知错误"
    return f"{label}（{period_key}，新签）: 失败，{detail}"
