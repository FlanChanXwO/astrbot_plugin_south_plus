from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from quart import Quart

from src.core.db import (
    CheckinSessionExclusionStore,
    CheckinStore,
    GroupStore,
    ScheduleStore,
    UserGroupStore,
    UserStore,
)
from src.pages import register_page_apis
from src.pages.handlers import SouthPlusPageApi


class _Context:
    def __init__(self) -> None:
        self.routes: list[tuple[str, Any, list[str], str]] = []

    def register_web_api(
        self,
        path: str,
        handler: Any,
        methods: list[str],
        description: str,
    ) -> None:
        self.routes.append((path, handler, methods, description))


@pytest.fixture()
def app() -> Quart:
    return Quart(__name__)


@pytest.fixture()
def stores(tmp_path: Path):
    db_path = tmp_path / "southplus.db"
    user_store = UserStore(db_path)
    group_store = GroupStore(db_path)
    user_group_store = UserGroupStore(db_path)
    schedule_store = ScheduleStore(db_path)
    checkin_store = CheckinStore(db_path)
    exclusion_store = CheckinSessionExclusionStore(db_path)
    scheduler = MagicMock()
    return {
        "user_store": user_store,
        "group_store": group_store,
        "user_group_store": user_group_store,
        "schedule_store": schedule_store,
        "checkin_store": checkin_store,
        "exclusion_store": exclusion_store,
        "scheduler": scheduler,
    }


@pytest.fixture()
def api(stores: dict[str, Any]) -> SouthPlusPageApi:
    return SouthPlusPageApi(**stores)


def _seed_user(user_store: UserStore, *, sp_uid: str = "2030219") -> None:
    user_store.add_or_update(
        sp_uid=sp_uid,
        account="10001",
        platform="aiocqhttp",
        cookie="super-secret-cookie",
    )


def test_register_page_apis_registers_expected_paths(stores: dict[str, Any]) -> None:
    context = _Context()
    register_page_apis(context, **stores)

    paths = {path for path, *_ in context.routes}

    assert paths == {
        "/astrbot_plugin_south_plus/dashboard/overview",
        "/astrbot_plugin_south_plus/accounts",
        "/astrbot_plugin_south_plus/accounts/delete",
        "/astrbot_plugin_south_plus/accounts/switch",
        "/astrbot_plugin_south_plus/accounts/auto-checkin",
        "/astrbot_plugin_south_plus/groups",
        "/astrbot_plugin_south_plus/user-groups",
        "/astrbot_plugin_south_plus/schedules",
        "/astrbot_plugin_south_plus/schedules/participants",
        "/astrbot_plugin_south_plus/schedules/participants/excluded",
        "/astrbot_plugin_south_plus/schedules/enabled",
        "/astrbot_plugin_south_plus/schedules/delete",
        "/astrbot_plugin_south_plus/checkins",
        "/astrbot_plugin_south_plus/suggestions",
    }


def test_dashboard_css_preserves_hidden_sections() -> None:
    css_path = Path(__file__).resolve().parents[1] / "pages/dashboard/css/dashboard.css"
    css = css_path.read_text(encoding="utf-8")

    assert "[hidden]" in css
    assert "display: none !important" in css


@pytest.mark.asyncio
async def test_accounts_list_never_exposes_plain_cookie(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"])

    async with app.test_request_context("/accounts"):
        response = await api.api_list_accounts()

    payload = await response.get_json()
    item = payload["items"][0]
    assert item["cookie_masked"]
    assert "cookie" not in item
    assert "super-secret-cookie" not in str(item)


@pytest.mark.asyncio
async def test_switch_account_requires_and_uses_platform(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    user_store: UserStore = stores["user_store"]
    _seed_user(user_store, sp_uid="uid-1")
    user_store.add_or_update(
        sp_uid="uid-2",
        account="10001",
        platform="aiocqhttp",
        cookie="cookie-2",
    )

    async with app.test_request_context(
        "/accounts/switch",
        method="POST",
        json={"account": "10001", "platform": "aiocqhttp", "sp_uid": "uid-1"},
    ):
        response = await api.api_switch_account()

    payload = await response.get_json()
    assert payload["switched"] is True
    assert user_store.get_active("10001", "aiocqhttp").sp_uid == "uid-1"


@pytest.mark.asyncio
async def test_delete_account_removes_user_group_links(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"], sp_uid="uid-1")
    group_id = stores["group_store"].upsert(
        bot_id="bot",
        platform="aiocqhttp",
        group_id="20001",
        group_name="group",
    )
    stores["user_group_store"].upsert(sp_uid="uid-1", group_id=group_id)

    async with app.test_request_context(
        "/accounts/delete",
        method="POST",
        json={"sp_uid": "uid-1"},
    ):
        response = await api.api_delete_account()

    payload = await response.get_json()
    assert payload["deleted"] is True
    assert stores["user_store"].get_by_uid("uid-1") is None
    assert stores["user_group_store"].get_groups_for_user("uid-1") == []


@pytest.mark.asyncio
async def test_schedule_enabled_refreshes_runtime_job(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    row = stores["schedule_store"].subscribe(
        umo="umo1",
        task_key="sp.checkin.all",
        cron="0 8 * * *",
        params_json='{"mode":"all"}',
    )

    async with app.test_request_context(
        "/schedules/enabled",
        method="POST",
        json={"id": row.id, "enabled": False},
    ):
        response = await api.api_set_schedule_enabled()

    payload = await response.get_json()
    assert payload["updated"] is True
    assert stores["schedule_store"].get_by_id(row.id).enabled is False
    stores["scheduler"].refresh_job.assert_called_once_with("umo1", "sp.checkin.all")


@pytest.mark.asyncio
async def test_schedule_delete_refreshes_runtime_job(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    row = stores["schedule_store"].subscribe(
        umo="umo2",
        task_key="sp.checkin.session",
        cron="0 8 * * *",
        params_json='{"mode":"session","account":"10001"}',
    )

    async with app.test_request_context(
        "/schedules/delete",
        method="POST",
        json={"id": row.id},
    ):
        response = await api.api_delete_schedule()

    payload = await response.get_json()
    assert payload["deleted"] is True
    assert stores["schedule_store"].get_by_id(row.id) is None
    stores["scheduler"].refresh_job.assert_called_once_with(
        "umo2", "sp.checkin.session"
    )


@pytest.mark.asyncio
async def test_schedule_participants_all_marks_session_exclusion(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"], sp_uid="uid-1")
    stores["user_store"].add_or_update(
        sp_uid="uid-2",
        account="10002",
        platform="aiocqhttp",
        cookie="cookie-2",
    )
    row = stores["schedule_store"].subscribe(
        umo="umo-all",
        task_key="sp.checkin.all",
        cron="0 8 * * *",
        params_json='{"mode":"all"}',
    )
    stores["exclusion_store"].exclude(umo="umo-all", sp_uid="uid-2")

    async with app.test_request_context(
        f"/schedules/participants?schedule_id={row.id}"
    ):
        response = await api.api_list_schedule_participants()

    payload = await response.get_json()
    by_uid = {item["sp_uid"]: item for item in payload["items"]}
    assert by_uid["uid-1"]["excluded"] is False
    assert by_uid["uid-1"]["will_run"] is True
    assert by_uid["uid-2"]["excluded"] is True
    assert by_uid["uid-2"]["will_run"] is False
    assert "cookie" not in by_uid["uid-2"]


@pytest.mark.asyncio
async def test_schedule_participants_session_uses_active_account(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"], sp_uid="uid-old")
    stores["user_store"].add_or_update(
        sp_uid="uid-active",
        account="10001",
        platform="aiocqhttp",
        cookie="cookie-active",
    )
    row = stores["schedule_store"].subscribe(
        umo="umo-session",
        task_key="sp.checkin.session",
        cron="0 8 * * *",
        params_json='{"mode":"session","account":"10001"}',
    )

    async with app.test_request_context(
        f"/schedules/participants?schedule_id={row.id}"
    ):
        response = await api.api_list_schedule_participants()

    payload = await response.get_json()
    assert [item["sp_uid"] for item in payload["items"]] == ["uid-active"]


@pytest.mark.asyncio
async def test_schedule_participant_excluded_updates_store_and_refreshes_jobs(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"], sp_uid="uid-1")
    row = stores["schedule_store"].subscribe(
        umo="umo-all",
        task_key="sp.checkin.all",
        cron="0 8 * * *",
        params_json='{"mode":"all"}',
    )

    async with app.test_request_context(
        "/schedules/participants/excluded",
        method="POST",
        json={"schedule_id": row.id, "sp_uid": "uid-1", "excluded": True},
    ):
        response = await api.api_set_schedule_participant_excluded()

    payload = await response.get_json()
    assert payload["updated"] is True
    assert stores["exclusion_store"].is_excluded(umo="umo-all", sp_uid="uid-1")
    stores["scheduler"].refresh_checkin_jobs.assert_called_once_with("umo-all")

    async with app.test_request_context(
        "/schedules/participants/excluded",
        method="POST",
        json={"schedule_id": row.id, "sp_uid": "uid-1", "excluded": False},
    ):
        response = await api.api_set_schedule_participant_excluded()

    payload = await response.get_json()
    assert payload["excluded"] is False
    assert not stores["exclusion_store"].is_excluded(umo="umo-all", sp_uid="uid-1")


@pytest.mark.asyncio
async def test_suggestions_returns_whitelisted_distinct_values(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    _seed_user(stores["user_store"], sp_uid="uid-1")
    stores["user_store"].add_or_update(
        sp_uid="uid-2",
        account="20002",
        platform="telegram",
        cookie="cookie-2",
    )

    async with app.test_request_context(
        "/suggestions?resource=accounts&field=keyword&q=uid&limit=5"
    ):
        response = await api.api_list_suggestions()

    payload = await response.get_json()
    values = {item["value"] for item in payload["items"]}
    assert {"uid-1", "uid-2"}.issubset(values)
    assert all(
        {"value", "label", "kind", "meta"} <= set(item) for item in payload["items"]
    )
    assert "cookie-2" not in str(payload)

    async with app.test_request_context(
        "/suggestions?resource=accounts&field=keyword&q=telegram&limit=5"
    ):
        response = await api.api_list_suggestions()

    payload = await response.get_json()
    assert any(item["value"] == "uid-2" for item in payload["items"])


@pytest.mark.asyncio
async def test_suggestions_rejects_unknown_field(
    app: Quart,
    api: SouthPlusPageApi,
) -> None:
    async with app.test_request_context(
        "/suggestions?resource=accounts&field=cookie&q=secret"
    ):
        response = await api.api_list_suggestions()

    response, status_code = response
    payload = await response.get_json()
    assert status_code == 400
    assert payload["ok"] is False


@pytest.mark.asyncio
async def test_checkin_history_filters(
    app: Quart,
    api: SouthPlusPageApi,
    stores: dict[str, Any],
) -> None:
    checkin_store: CheckinStore = stores["checkin_store"]
    checkin_store.record(
        sp_uid="uid-1",
        task_key="sp.checkin.daily",
        period_key="2026-06-06",
        status="success",
        message="OK",
    )
    checkin_store.record(
        sp_uid="uid-2",
        task_key="sp.checkin.weekly",
        period_key="2026-W23",
        status="failed",
        message="NO",
        error="boom",
    )

    async with app.test_request_context("/checkins?status=failed&limit=10"):
        response = await api.api_list_checkins()

    payload = await response.get_json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["sp_uid"] == "uid-2"
    assert payload["items"][0]["error"] == "boom"
