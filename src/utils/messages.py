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
    """格式化一次日签 + 周签的用户可见结果。

    ``today`` 和 ``this_week_label`` 仍保留在签名中，避免命令层为了文案调整
    频繁改变调用契约；用户侧不展示本地缓存/周期 key 这类实现细节。
    """
    daily_failed = _checkin_status_value(fresh_daily) == "failed"
    weekly_failed = _checkin_status_value(fresh_weekly) == "failed"
    completed = 0 if daily_failed or weekly_failed else 1
    lines = [
        "South Plus 主动签到",
        "南+账号：1 个",
        f"UID：{uid}",
        f"完成 {completed}：✅ 成功 {completed}",
        _format_dimension_line(label="社区·日签", fresh=fresh_daily),
        _format_dimension_line(label="社区·周签", fresh=fresh_weekly),
    ]
    return "\n".join(lines)


def _format_dimension_line(
    *,
    label: str,
    fresh: "CheckinTaskResult | None",
) -> str:
    status = _checkin_status_value(fresh)
    if status == "success":
        return f"{label}：✅ 成功"
    if status == "already_done":
        return f"{label}：⏭️ 请勿重复签到"
    detail = fresh.message or fresh.error or "未知错误"
    return f"{label}：❌ 失败，{detail}"


def _checkin_status_value(fresh: "CheckinTaskResult | None") -> str:
    if fresh is None:
        return "already_done"
    status = fresh.status
    return getattr(status, "value", status)
