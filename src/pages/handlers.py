"""South Plus Plugin Pages Web API handlers。"""

from __future__ import annotations

from typing import Any

from quart import jsonify, request

from ..core.checkin_scheduler import CheckinScheduler
from ..core.db import (
    CheckinSessionExclusionStore,
    CheckinStore,
    GroupStore,
    ScheduleStore,
    UserGroupStore,
    UserStore,
)
from ..shared.constants import PLUGIN_NAME
from .dto import error_response, ok_response
from .queries import (
    build_overview,
    build_schedule_participants,
    build_suggestions,
    build_user_group_rows,
    checkins_to_dict,
    filter_groups,
    filter_schedules,
    filter_users,
)


class SouthPlusPageApi:
    """集中管理 Plugin Pages 后端 API。"""

    def __init__(
        self,
        *,
        user_store: UserStore,
        group_store: GroupStore,
        user_group_store: UserGroupStore,
        schedule_store: ScheduleStore,
        checkin_store: CheckinStore,
        exclusion_store: CheckinSessionExclusionStore,
        scheduler: CheckinScheduler,
    ) -> None:
        self.user_store = user_store
        self.group_store = group_store
        self.user_group_store = user_group_store
        self.schedule_store = schedule_store
        self.checkin_store = checkin_store
        self.exclusion_store = exclusion_store
        self.scheduler = scheduler

    def register(self, context: Any) -> None:
        """注册所有 Dashboard API 路由。"""
        routes = [
            ("dashboard/overview", self.api_overview, ["GET"], "Dashboard overview"),
            ("accounts", self.api_list_accounts, ["GET"], "List accounts"),
            ("accounts/delete", self.api_delete_account, ["POST"], "Delete account"),
            ("accounts/switch", self.api_switch_account, ["POST"], "Switch account"),
            (
                "accounts/auto-checkin",
                self.api_set_auto_checkin,
                ["POST"],
                "Set auto checkin",
            ),
            ("groups", self.api_list_groups, ["GET"], "List groups"),
            ("user-groups", self.api_list_user_groups, ["GET"], "List user groups"),
            ("schedules", self.api_list_schedules, ["GET"], "List schedules"),
            (
                "schedules/participants",
                self.api_list_schedule_participants,
                ["GET"],
                "List schedule participants",
            ),
            (
                "schedules/participants/excluded",
                self.api_set_schedule_participant_excluded,
                ["POST"],
                "Set schedule participant exclusion",
            ),
            (
                "schedules/enabled",
                self.api_set_schedule_enabled,
                ["POST"],
                "Set schedule enabled",
            ),
            ("schedules/delete", self.api_delete_schedule, ["POST"], "Delete schedule"),
            ("checkins", self.api_list_checkins, ["GET"], "List checkins"),
            ("suggestions", self.api_list_suggestions, ["GET"], "List suggestions"),
        ]
        for path, handler, methods, description in routes:
            context.register_web_api(
                f"/{PLUGIN_NAME}/{path}",
                handler,
                methods,
                description,
            )

    async def api_overview(self):
        checkins = self.checkin_store.list_recent(limit=200)
        return jsonify(
            ok_response(
                overview=build_overview(
                    users=self.user_store.list_all(),
                    groups=self.group_store.list_all(),
                    schedules=self.schedule_store.list_all(),
                    checkins=checkins,
                )
            )
        )

    async def api_list_accounts(self):
        return jsonify(
            ok_response(
                items=filter_users(
                    self.user_store.list_all(),
                    keyword=_arg("keyword"),
                    platform=_arg("platform"),
                    account=_arg("account"),
                    active=_arg("active"),
                    auto_checkin=_arg("auto_checkin"),
                )
            )
        )

    async def api_delete_account(self):
        payload = await _json_payload()
        sp_uid = str(payload.get("sp_uid") or payload.get("uid") or "").strip()
        if not sp_uid:
            return jsonify(error_response("sp_uid 必填")), 400
        user = self.user_store.get_by_uid(sp_uid)
        if user is None:
            return jsonify(error_response("账号不存在")), 404
        self.user_group_store.delete_by_user(sp_uid)
        ok = self.user_store.delete_account(account=user.account, sp_uid=sp_uid)
        return jsonify(ok_response(deleted=ok))

    async def api_switch_account(self):
        payload = await _json_payload()
        account = str(payload.get("account") or payload.get("user_key") or "").strip()
        platform = str(payload.get("platform") or "").strip()
        sp_uid = str(payload.get("sp_uid") or payload.get("uid") or "").strip()
        if not account or not platform or not sp_uid:
            return jsonify(error_response("account、platform 与 sp_uid 必填")), 400
        ok = self.user_store.switch_active(
            account=account,
            platform=platform,
            sp_uid=sp_uid,
        )
        return jsonify(ok_response(switched=ok))

    async def api_set_auto_checkin(self):
        payload = await _json_payload()
        sp_uid = str(payload.get("sp_uid") or "").strip()
        if not sp_uid:
            return jsonify(error_response("sp_uid 必填")), 400
        enabled = _payload_bool(payload.get("enabled"))
        ok = self.user_store.set_auto_checkin(sp_uid, enabled)
        return jsonify(ok_response(updated=ok))

    async def api_list_groups(self):
        return jsonify(
            ok_response(
                items=filter_groups(
                    self.group_store.list_all(),
                    keyword=_arg("keyword"),
                    platform=_arg("platform"),
                    bot_id=_arg("bot_id"),
                )
            )
        )

    async def api_list_user_groups(self):
        return jsonify(
            ok_response(
                items=build_user_group_rows(
                    self.user_group_store.list_all(),
                    users=self.user_store.list_all(),
                    groups=self.group_store.list_all(),
                    sp_uid=_arg("sp_uid"),
                    group_id=_arg("group_id"),
                )
            )
        )

    async def api_list_schedules(self):
        return jsonify(
            ok_response(
                items=filter_schedules(
                    self.schedule_store.list_all(),
                    keyword=_arg("keyword"),
                    umo=_arg("umo"),
                    task_key=_arg("task_key"),
                    enabled=_arg("enabled"),
                )
            )
        )

    async def api_list_schedule_participants(self):
        schedule_id = _payload_int(_arg("schedule_id") or _arg("id"))
        if schedule_id <= 0:
            return jsonify(error_response("schedule_id 必填")), 400
        row = self.schedule_store.get_by_id(schedule_id)
        if row is None:
            return jsonify(error_response("调度不存在")), 404
        return jsonify(
            ok_response(
                schedule_id=row.id,
                umo=row.umo,
                task_key=row.task_key,
                items=build_schedule_participants(
                    row,
                    users=self.user_store.list_all(),
                    excluded_uids=self.exclusion_store.list_uids(row.umo),
                    keyword=_arg("keyword"),
                    excluded=_arg("excluded"),
                ),
            )
        )

    async def api_set_schedule_participant_excluded(self):
        payload = await _json_payload()
        schedule_id = _payload_int(payload.get("schedule_id") or payload.get("id"))
        sp_uid = str(payload.get("sp_uid") or "").strip()
        if schedule_id <= 0 or not sp_uid:
            return jsonify(error_response("schedule_id 与 sp_uid 必填")), 400
        row = self.schedule_store.get_by_id(schedule_id)
        if row is None:
            return jsonify(error_response("调度不存在")), 404
        if self.user_store.get_by_uid(sp_uid) is None:
            return jsonify(error_response("账号不存在")), 404

        excluded = _payload_bool(payload.get("excluded"))
        if excluded:
            self.exclusion_store.exclude(umo=row.umo, sp_uid=sp_uid)
        else:
            self.exclusion_store.restore(umo=row.umo, sp_uid=sp_uid)
        self.scheduler.refresh_checkin_jobs(row.umo)
        return jsonify(ok_response(updated=True, excluded=excluded))

    async def api_set_schedule_enabled(self):
        payload = await _json_payload()
        schedule_id = _payload_int(payload.get("id"))
        if schedule_id <= 0:
            return jsonify(error_response("id 必填")), 400
        row = self.schedule_store.get_by_id(schedule_id)
        if row is None:
            return jsonify(error_response("调度不存在")), 404
        enabled = _payload_bool(payload.get("enabled"))
        self.schedule_store.set_enabled(schedule_id, enabled)
        self.scheduler.refresh_job(row.umo, row.task_key)
        return jsonify(ok_response(updated=True))

    async def api_delete_schedule(self):
        payload = await _json_payload()
        schedule_id = _payload_int(payload.get("id"))
        if schedule_id <= 0:
            return jsonify(error_response("id 必填")), 400
        row = self.schedule_store.get_by_id(schedule_id)
        if row is None:
            return jsonify(error_response("调度不存在")), 404
        deleted = self.schedule_store.delete_by_id(schedule_id)
        self.scheduler.refresh_job(row.umo, row.task_key)
        return jsonify(ok_response(deleted=deleted))

    async def api_list_checkins(self):
        limit = _payload_int(_arg("limit"), default=100)
        return jsonify(
            ok_response(
                items=checkins_to_dict(
                    self.checkin_store.list_recent(
                        sp_uid=_arg("sp_uid"),
                        task_key=_arg("task_key"),
                        status=_arg("status"),
                        period_key=_arg("period_key"),
                        limit=limit,
                    )
                )
            )
        )

    async def api_list_suggestions(self):
        resource = _arg("resource")
        field = _arg("field")
        keyword = _arg("q") or _arg("keyword")
        limit = _payload_int(_arg("limit"), default=12)
        try:
            items = build_suggestions(
                resource=resource,
                field=field,
                keyword=keyword,
                limit=limit,
                users=self.user_store.list_all(),
                groups=self.group_store.list_all(),
                schedules=self.schedule_store.list_all(),
                checkins=self.checkin_store.list_recent(limit=300),
                relations=self.user_group_store.list_all(),
            )
        except ValueError as exc:
            return jsonify(error_response(str(exc))), 400
        return jsonify(ok_response(items=items))


async def _json_payload() -> dict[str, Any]:
    payload = await request.get_json(force=True, silent=True)
    return payload if isinstance(payload, dict) else {}


def _arg(name: str) -> str:
    return str(request.args.get(name, "") or "").strip()


def _payload_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "是"}


def _payload_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
