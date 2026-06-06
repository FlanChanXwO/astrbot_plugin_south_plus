"""Dashboard 查询与筛选 helper。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from ..core.datamodels import CheckinRow, GroupRow, ScheduleRow, UserGroupRow, UserRow
from .dto import (
    checkin_to_dict,
    group_to_dict,
    parse_params_json,
    schedule_to_dict,
    user_group_to_dict,
    user_to_public_dict,
)


def filter_users(
    rows: list[UserRow],
    *,
    keyword: str = "",
    platform: str = "",
    account: str = "",
    active: str = "",
    auto_checkin: str = "",
) -> list[dict[str, Any]]:
    filtered = rows
    if keyword:
        filtered = [
            row
            for row in filtered
            if _contains(row.sp_uid, keyword)
            or _contains(row.account, keyword)
            or _contains(row.platform, keyword)
        ]
    if platform:
        filtered = [row for row in filtered if row.platform == platform]
    if account:
        filtered = [row for row in filtered if row.account == account]
    if active:
        value = _bool_filter(active)
        filtered = [row for row in filtered if row.is_active is value]
    if auto_checkin:
        value = _bool_filter(auto_checkin)
        filtered = [row for row in filtered if row.auto_checkin is value]
    return [user_to_public_dict(row) for row in filtered]


def filter_groups(
    rows: list[GroupRow],
    *,
    keyword: str = "",
    platform: str = "",
    bot_id: str = "",
) -> list[dict[str, Any]]:
    filtered = rows
    if keyword:
        filtered = [
            row
            for row in filtered
            if _contains(row.group_id, keyword)
            or _contains(row.group_name, keyword)
            or _contains(row.platform, keyword)
            or _contains(row.bot_id, keyword)
        ]
    if platform:
        filtered = [row for row in filtered if row.platform == platform]
    if bot_id:
        filtered = [row for row in filtered if row.bot_id == bot_id]
    return [group_to_dict(row) for row in filtered]


def build_user_group_rows(
    links: list[UserGroupRow],
    *,
    users: list[UserRow],
    groups: list[GroupRow],
    sp_uid: str = "",
    group_id: str = "",
) -> list[dict[str, Any]]:
    users_by_uid = {row.sp_uid: row for row in users}
    groups_by_id = {row.id: row for row in groups}
    result: list[dict[str, Any]] = []
    for link in links:
        if sp_uid and link.sp_uid != sp_uid:
            continue
        if group_id and str(link.group_id) != group_id:
            continue
        payload = user_group_to_dict(link)
        user = users_by_uid.get(link.sp_uid)
        group = groups_by_id.get(link.group_id)
        payload["account"] = user.account if user else ""
        payload["platform"] = group.platform if group else ""
        payload["group_external_id"] = group.group_id if group else ""
        payload["group_name"] = group.group_name if group else ""
        result.append(payload)
    return result


def filter_schedules(
    rows: list[ScheduleRow],
    *,
    keyword: str = "",
    umo: str = "",
    task_key: str = "",
    enabled: str = "",
) -> list[dict[str, Any]]:
    filtered = rows
    if keyword:
        filtered = [
            row
            for row in filtered
            if _contains(row.umo, keyword)
            or _contains(row.task_key, keyword)
            or _contains(row.cron, keyword)
            or _contains(row.params_json, keyword)
        ]
    if umo:
        filtered = [row for row in filtered if row.umo == umo]
    if task_key:
        filtered = [row for row in filtered if row.task_key == task_key]
    if enabled:
        value = _bool_filter(enabled)
        filtered = [row for row in filtered if row.enabled is value]
    return [schedule_to_dict(row) for row in filtered]


def build_schedule_participants(
    schedule: ScheduleRow,
    *,
    users: list[UserRow],
    excluded_uids: set[str],
    keyword: str = "",
    excluded: str = "",
) -> list[dict[str, Any]]:
    """按 scheduler 实际收集语义构造某个调度的参与账号列表。"""
    params = parse_params_json(schedule.params_json)
    mode = str(params.get("mode") or "session")
    participants = (
        users
        if mode == "all"
        else _active_users_for_account(users, str(params.get("account") or ""))
    )

    rows: list[dict[str, Any]] = []
    excluded_filter = _optional_bool_filter(excluded)
    for user in participants:
        is_excluded = user.sp_uid in excluded_uids
        if excluded_filter is not None and is_excluded is not excluded_filter:
            continue
        if keyword and not (
            _contains(user.sp_uid, keyword)
            or _contains(user.account, keyword)
            or _contains(user.platform, keyword)
        ):
            continue
        payload = user_to_public_dict(user)
        payload["excluded"] = is_excluded
        payload["will_run"] = user.auto_checkin and not is_excluded
        rows.append(payload)
    return rows


def build_suggestions(
    *,
    resource: str,
    field: str,
    keyword: str,
    limit: int,
    users: list[UserRow],
    groups: list[GroupRow],
    schedules: list[ScheduleRow],
    checkins: list[CheckinRow],
    relations: list[UserGroupRow],
) -> list[dict[str, Any]]:
    """服务端补全候选，只允许白名单 resource/field。"""
    suggestions = _suggestion_values(
        resource=resource,
        field=field,
        users=users,
        groups=groups,
        schedules=schedules,
        checkins=checkins,
        relations=relations,
    )
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for suggestion in suggestions:
        value = str(suggestion.get("value") or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        haystack = " ".join(
            [
                value,
                str(suggestion.get("label") or ""),
                str(suggestion.get("kind") or ""),
                " ".join(str(item) for item in (suggestion.get("meta") or {}).values()),
            ]
        )
        if keyword and not _contains(haystack, keyword):
            continue
        seen.add(key)
        items.append(suggestion)
        if len(items) >= max(1, limit):
            break
    return items


def checkins_to_dict(rows: list[CheckinRow]) -> list[dict[str, Any]]:
    return [checkin_to_dict(row) for row in rows]


def build_overview(
    *,
    users: list[UserRow],
    groups: list[GroupRow],
    schedules: list[ScheduleRow],
    checkins: list[CheckinRow],
) -> dict[str, Any]:
    status_counts = Counter(row.status for row in checkins)
    return {
        "accounts_total": len(users),
        "accounts_active": sum(1 for row in users if row.is_active),
        "accounts_auto_checkin": sum(1 for row in users if row.auto_checkin),
        "groups_total": len(groups),
        "schedules_total": len(schedules),
        "schedules_enabled": sum(1 for row in schedules if row.enabled),
        "checkins_recent": len(checkins),
        "checkins_by_status": dict(status_counts),
    }


def _contains(value: object, keyword: str) -> bool:
    return keyword.lower() in str(value or "").lower()


def _bool_filter(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "是"}


def _optional_bool_filter(value: str) -> bool | None:
    return _bool_filter(value) if value else None


def _active_users_for_account(users: list[UserRow], account: str) -> list[UserRow]:
    if not account:
        return []
    return [user for user in users if user.account == account and user.is_active]


def _suggestion_values(
    *,
    resource: str,
    field: str,
    users: list[UserRow],
    groups: list[GroupRow],
    schedules: list[ScheduleRow],
    checkins: list[CheckinRow],
    relations: list[UserGroupRow],
) -> Iterable[dict[str, Any]]:
    account_keyword = [
        item
        for user in users
        for item in (
            _suggestion(
                value=user.sp_uid,
                label=user.sp_uid,
                kind="UID",
                meta={"account": user.account, "platform": user.platform},
            ),
            _suggestion(
                value=user.account,
                label=user.account,
                kind="用户",
                meta={"uid": user.sp_uid, "platform": user.platform},
            ),
            _suggestion(
                value=user.platform,
                label=user.platform,
                kind="平台",
                meta={"account": user.account},
            ),
        )
    ]
    group_keyword = [
        item
        for group in groups
        for item in (
            _suggestion(
                value=group.group_id,
                label=group.group_id,
                kind="群号",
                meta={"name": group.group_name, "platform": group.platform},
            ),
            _suggestion(
                value=group.group_name,
                label=group.group_name,
                kind="群名",
                meta={"group_id": group.group_id, "platform": group.platform},
            ),
            _suggestion(
                value=group.platform,
                label=group.platform,
                kind="平台",
                meta={"group_id": group.group_id},
            ),
            _suggestion(
                value=group.bot_id,
                label=group.bot_id,
                kind="Bot",
                meta={"platform": group.platform},
            ),
        )
    ]
    schedule_keyword = [
        item
        for schedule in schedules
        for item in (
            _suggestion(
                value=schedule.umo,
                label=schedule.umo,
                kind="会话",
                meta={"task": schedule.task_key},
            ),
            _suggestion(
                value=schedule.task_key,
                label=schedule.task_key,
                kind="任务",
                meta={"umo": schedule.umo},
            ),
            _suggestion(
                value=schedule.cron,
                label=schedule.cron,
                kind="Cron",
                meta={"task": schedule.task_key},
            ),
        )
    ]
    allowed = {
        "accounts": {
            "keyword": account_keyword,
            "sp_uid": [
                _suggestion(value=u.sp_uid, label=u.sp_uid, kind="UID") for u in users
            ],
            "account": [
                _suggestion(value=u.account, label=u.account, kind="用户")
                for u in users
            ],
            "platform": [
                _suggestion(value=u.platform, label=u.platform, kind="平台")
                for u in users
            ],
        },
        "groups": {
            "keyword": group_keyword,
            "platform": [
                _suggestion(value=g.platform, label=g.platform, kind="平台")
                for g in groups
            ],
            "bot_id": [
                _suggestion(value=g.bot_id, label=g.bot_id, kind="Bot") for g in groups
            ],
        },
        "schedules": {
            "keyword": schedule_keyword,
            "umo": [
                _suggestion(value=s.umo, label=s.umo, kind="会话") for s in schedules
            ],
            "task_key": [
                _suggestion(value=s.task_key, label=s.task_key, kind="任务")
                for s in schedules
            ],
        },
        "checkins": {
            "sp_uid": [
                _suggestion(value=c.sp_uid, label=c.sp_uid, kind="UID")
                for c in checkins
            ],
            "task_key": [
                _suggestion(value=c.task_key, label=c.task_key, kind="任务")
                for c in checkins
            ],
            "status": [
                _suggestion(value=c.status, label=c.status, kind="状态")
                for c in checkins
            ],
            "period_key": [
                _suggestion(value=c.period_key, label=c.period_key, kind="周期")
                for c in checkins
            ],
        },
        "relations": {
            "sp_uid": [
                _suggestion(value=r.sp_uid, label=r.sp_uid, kind="UID")
                for r in relations
            ],
            "group_id": [
                _suggestion(value=r.group_id, label=r.group_id, kind="群 ID")
                for r in relations
            ],
        },
        "participants": {
            "keyword": account_keyword,
        },
    }
    if resource not in allowed or field not in allowed[resource]:
        raise ValueError("不支持的补全字段")
    return allowed[resource][field]


def _suggestion(
    *,
    value: Any,
    label: Any,
    kind: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(value or "").strip()
    return {
        "value": normalized,
        "label": str(label or normalized).strip(),
        "kind": kind,
        "meta": meta or {},
    }
