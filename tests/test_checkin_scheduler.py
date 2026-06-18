"""新 ``CheckinScheduler`` 测试。

覆盖：生命周期、订阅管理、全量签到、helper 函数。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.checkin_scheduler import (
    CheckinScheduler,
    _PerUserResult,
    _format_aggregated_report,
    _format_global_report,
    _is_failed,
)
from src.core.datamodels import ScheduleRow, UserRow
from src.core.tasks.base import TaskResult
from src.southplus.models import CheckinReport, CheckinStatus, CheckinTaskResult


def _make_user(
    sp_uid: str = "12345",
    account: str = "10001",
    platform: str = "aiocqhttp",
    cookie: str = "fake_cookie",
) -> UserRow:
    return UserRow(
        sp_uid=sp_uid,
        account=account,
        platform=platform,
        cookie=cookie,
        is_active=True,
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )


def _make_per_user_result(
    sp_uid: str = "12345",
    account: str = "10001",
    status: str = CheckinStatus.SUCCESS.value,
    message: str = "OK",
    skipped: bool = False,
    daily_status: str = "",
    weekly_status: str = "",
) -> _PerUserResult:
    if not daily_status and not weekly_status:
        # 向后兼容：无维度时默认日签=success
        daily_status = status
    return _PerUserResult(
        user=_make_user(sp_uid=sp_uid, account=account),
        result=TaskResult(status=status, message=message),
        skipped=skipped,
        daily_status=daily_status,
        weekly_status=weekly_status,
    )


def _make_scheduler(
    user_store: MagicMock | None = None,
    checkin_store: MagicMock | None = None,
    schedule_store: MagicMock | None = None,
    exclusion_store: MagicMock | None = None,
) -> CheckinScheduler:
    service = MagicMock()
    ustore = user_store or MagicMock()
    cstore = checkin_store or MagicMock()
    cstore.is_already_done.return_value = False
    if checkin_store is None:
        cstore.get_genuine_status.return_value = None
    sstore = schedule_store or MagicMock()
    send_message = AsyncMock()
    return CheckinScheduler(
        checkin_service=service,
        user_store=ustore,
        checkin_store=cstore,
        schedule_store=sstore,
        send_message=send_message,
        exclusion_store=exclusion_store,
    )


def _make_schedule(
    *,
    id: int = 1,
    umo: str = "umo1",
    task_key: str = "sp.checkin.all",
    params_json: str = '{"mode":"all"}',
    enabled: bool = True,
) -> ScheduleRow:
    return ScheduleRow(
        id=id,
        umo=umo,
        task_key=task_key,
        cron="0 8 * * *",
        params_json=params_json,
        enabled=enabled,
        created_at="2026-06-06",
        updated_at="2026-06-06",
    )


def _assert_subscription_report_lines(
    text: str,
    *,
    title: str,
    total: int,
    completed: int,
    daily_line: str,
    weekly_line: str,
) -> None:
    lines = text.splitlines()
    assert lines[0] == title
    assert f"南+账号：{total} 个" in lines
    assert f"完成 {completed}：✅ 成功 {completed}" in lines
    assert daily_line in lines
    assert weekly_line in lines


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_scheduler(self) -> None:
        scheduler = _make_scheduler()
        scheduler.start(concurrency=3)
        assert scheduler._scheduler is not None
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_scheduler(self) -> None:
        scheduler = _make_scheduler()
        scheduler.start(concurrency=3)
        scheduler.stop()
        assert scheduler._scheduler is None

    def test_stop_idempotent(self) -> None:
        scheduler = _make_scheduler()
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_start_replaces_existing(self) -> None:
        scheduler = _make_scheduler()
        scheduler.start(concurrency=3)
        first = scheduler._scheduler
        scheduler.start(concurrency=5)
        assert scheduler._scheduler is not first
        scheduler.stop()

    def test_reload_config_updates_checkin_cron_and_rebuilds_jobs(self) -> None:
        sstore = MagicMock()
        sstore.batch_update_cron.return_value = ["umo1"]
        sstore.list_by_umo.return_value = [
            _make_schedule(id=1, umo="umo1", task_key="sp.checkin.all"),
            _make_schedule(id=2, umo="umo1", task_key="sp.checkin.session"),
            _make_schedule(id=3, umo="umo1", task_key="custom.task"),
            _make_schedule(
                id=4, umo="umo1", task_key="sp.checkin.daily", enabled=False
            ),
        ]
        scheduler = _make_scheduler(schedule_store=sstore)

        with patch.object(scheduler, "_ensure_job_for") as mock_ensure:
            scheduler.reload_config(cron="0 3 * * *", concurrency=5)

        sstore.batch_update_cron.assert_called_once_with(
            task_key_prefix="sp.checkin.",
            new_cron="0 3 * * *",
        )
        assert scheduler._semaphore is not None
        assert {call.args for call in mock_ensure.call_args_list} == {
            ("umo1", "sp.checkin.all"),
            ("umo1", "sp.checkin.session"),
            ("umo1", "custom.task"),
        }


# ---------------------------------------------------------------------------
# 订阅管理
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_session(self) -> None:
        sstore = MagicMock()
        sstore.list_by_umo.return_value = []
        scheduler = _make_scheduler(schedule_store=sstore)
        scheduler.subscribe(
            "umo1",
            task_key="sp.checkin.daily",
            cron="0 8 * * *",
            params={"mode": "session", "account": "u1"},
        )
        sstore.subscribe.assert_called_once()

    def test_unsubscribe(self) -> None:
        sstore = MagicMock()
        scheduler = _make_scheduler(schedule_store=sstore)
        scheduler.unsubscribe(
            "umo1",
            task_key="sp.checkin.daily",
            params={"mode": "session", "account": "u1"},
        )
        sstore.unsubscribe.assert_called_once()

    def test_is_subscribed(self) -> None:
        sstore = MagicMock()
        sstore.is_subscribed.return_value = True
        scheduler = _make_scheduler(schedule_store=sstore)
        assert scheduler.is_subscribed(
            "umo1",
            task_key="sp.checkin.daily",
            params={"mode": "session", "account": "u1"},
        )


# ---------------------------------------------------------------------------
# 全量签到
# ---------------------------------------------------------------------------


class TestRunAllCheckins:
    @pytest.mark.asyncio
    async def test_empty_accounts(self) -> None:
        ustore = MagicMock()
        ustore.list_all.return_value = []
        scheduler = _make_scheduler(user_store=ustore)
        text = await scheduler.run_all_checkins()
        assert "无绑定账号" in text
        assert text.startswith("South Plus 主动签到（全体账号）")

    @pytest.mark.asyncio
    async def test_single_account_success(self) -> None:
        user = _make_user()
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        cstore = MagicMock()
        cstore.is_already_done.return_value = False
        cstore.get_genuine_status.return_value = None

        scheduler = _make_scheduler(user_store=ustore, checkin_store=cstore)
        with patch.object(
            scheduler, "_do_checkin_both", new_callable=AsyncMock
        ) as mock_do:
            mock_do.return_value = _PerUserResult(
                user=user,
                result=TaskResult(status=CheckinStatus.SUCCESS.value, message="OK"),
                skipped=False,
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            )
            text = await scheduler.run_all_checkins()
        assert text.splitlines() == [
            "South Plus 主动签到（全体账号）",
            "南+账号：1 个",
            "完成 1：✅ 成功 1",
            "社区·日签：✅ 1  ⏭️ 请勿重复签到 0  ❌ 0",
            "社区·周签：✅ 1  ⏭️ 请勿重复签到 0  ❌ 0",
        ]

    @pytest.mark.asyncio
    async def test_first_checkin_success_counts_as_ok_in_subscription_report(
        self,
    ) -> None:
        user = _make_user()
        cstore = MagicMock()
        cstore.is_already_done.return_value = False
        cstore.get_genuine_status.return_value = None
        scheduler = _make_scheduler(checkin_store=cstore)
        scheduler._checkin_service.checkin.return_value = CheckinReport(
            daily=CheckinTaskResult(
                status=CheckinStatus.SUCCESS,
                message="日签：领取成功",
            ),
            weekly=CheckinTaskResult(
                status=CheckinStatus.SUCCESS,
                message="周签：领取成功",
            ),
        )

        result = await scheduler._do_checkin_both(user)

        assert result is not None
        assert result.daily_status == CheckinStatus.SUCCESS.value
        assert result.weekly_status == CheckinStatus.SUCCESS.value
        text, failed = _format_aggregated_report(
            [result], task_key="sp.checkin.session"
        )
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（会话订阅）",
            total=1,
            completed=1,
            daily_line="社区·日签：✅ 1  ⏭️ 0  ❌ 0",
            weekly_line="社区·周签：✅ 1  ⏭️ 0  ❌ 0",
        )
        assert failed == []

    @pytest.mark.asyncio
    async def test_cached_success_counts_as_ok_in_subscription_report(self) -> None:
        user = _make_user()
        cstore = MagicMock()
        cstore.get_genuine_status.return_value = CheckinStatus.SUCCESS.value
        scheduler = _make_scheduler(checkin_store=cstore)
        cstore.is_already_done.return_value = True

        result = await scheduler._do_checkin_both(user)

        assert result is not None
        assert result.daily_status == CheckinStatus.SUCCESS.value
        assert result.weekly_status == CheckinStatus.SUCCESS.value
        scheduler._checkin_service.checkin.assert_not_called()
        text, failed = _format_aggregated_report(
            [result], task_key="sp.checkin.session"
        )
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（会话订阅）",
            total=1,
            completed=1,
            daily_line="社区·日签：✅ 1  ⏭️ 0  ❌ 0",
            weekly_line="社区·周签：✅ 1  ⏭️ 0  ❌ 0",
        )
        assert failed == []

    @pytest.mark.asyncio
    async def test_cached_already_done_counts_as_skip_in_subscription_report(
        self,
    ) -> None:
        user = _make_user()
        cstore = MagicMock()
        cstore.get_genuine_status.return_value = CheckinStatus.ALREADY_DONE.value
        scheduler = _make_scheduler(checkin_store=cstore)
        cstore.is_already_done.return_value = True

        result = await scheduler._do_checkin_both(user)

        assert result is not None
        assert result.daily_status == CheckinStatus.ALREADY_DONE.value
        assert result.weekly_status == CheckinStatus.ALREADY_DONE.value
        scheduler._checkin_service.checkin.assert_not_called()
        text, failed = _format_aggregated_report(
            [result], task_key="sp.checkin.session"
        )
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（会话订阅）",
            total=1,
            completed=1,
            daily_line="社区·日签：✅ 0  ⏭️ 1  ❌ 0",
            weekly_line="社区·周签：✅ 0  ⏭️ 1  ❌ 0",
        )
        assert failed == []

    @pytest.mark.asyncio
    async def test_cached_daily_success_and_fresh_weekly_success_count_as_ok(
        self,
    ) -> None:
        user = _make_user()
        cstore = MagicMock()

        def cached_status(*, task_key: str, **_: str) -> str | None:
            if task_key == "sp.checkin.daily":
                return CheckinStatus.SUCCESS.value
            return None

        cstore.get_genuine_status.side_effect = cached_status
        scheduler = _make_scheduler(checkin_store=cstore)
        cstore.is_already_done.side_effect = lambda *, task_key, **_: (
            task_key == ("sp.checkin.daily")
        )
        scheduler._checkin_service.checkin_weekly.return_value = CheckinTaskResult(
            status=CheckinStatus.SUCCESS,
            message="周签：领取成功",
        )

        result = await scheduler._do_checkin_both(user)

        assert result is not None
        assert result.daily_status == CheckinStatus.SUCCESS.value
        assert result.weekly_status == CheckinStatus.SUCCESS.value
        scheduler._checkin_service.checkin.assert_not_called()
        scheduler._checkin_service.checkin_weekly.assert_called_once_with(user.cookie)
        text, failed = _format_aggregated_report(
            [result], task_key="sp.checkin.session"
        )
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（会话订阅）",
            total=1,
            completed=1,
            daily_line="社区·日签：✅ 1  ⏭️ 0  ❌ 0",
            weekly_line="社区·周签：✅ 1  ⏭️ 0  ❌ 0",
        )
        assert failed == []


class TestSessionExclusion:
    @pytest.mark.asyncio
    async def test_all_mode_uses_session_subscription_uid_union(self) -> None:
        users = [
            _make_user(sp_uid="uid-1", account="u1"),
            _make_user(sp_uid="uid-2", account="u2"),
            _make_user(sp_uid="uid-3", account="u3"),
        ]
        ustore = MagicMock()
        ustore.list_all.return_value = users
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(umo="global-umo", task_key="sp.checkin.all")
        ]
        sstore.list_all_enabled.return_value = [
            _make_schedule(
                umo="session-a",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
            _make_schedule(
                umo="session-b",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u2"}',
            ),
            _make_schedule(umo="global-umo", task_key="sp.checkin.all"),
        ]
        estore = MagicMock()
        estore.list_uids.return_value = set()
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_checkin.side_effect = lambda user, _semaphore: _make_per_user_result(
                sp_uid=user.sp_uid,
                account=user.account,
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            )
            await scheduler._tick_for_key("global-umo", "sp.checkin.all")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1",
            "uid-2",
        ]
        mock_push.assert_awaited_once()
        assert mock_push.await_args.args[0] == "global-umo"
        assert mock_push.await_args.args[1] == "sp.checkin.all"

    @pytest.mark.asyncio
    async def test_all_mode_deduplicates_same_uid_from_multiple_sessions(
        self,
    ) -> None:
        user = _make_user(sp_uid="uid-1", account="u1")
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(umo="global-umo", task_key="sp.checkin.all")
        ]
        sstore.list_all_enabled.return_value = [
            _make_schedule(
                umo="session-a",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
            _make_schedule(
                umo="session-b",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
        ]
        estore = MagicMock()
        estore.list_uids.return_value = set()
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_checkin.return_value = _make_per_user_result(sp_uid="uid-1")
            await scheduler._tick_for_key("global-umo", "sp.checkin.all")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1"
        ]
        mock_push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_mode_caches_exclusions_per_session_umo(self) -> None:
        users = [
            _make_user(sp_uid="uid-1", account="u1"),
            _make_user(sp_uid="uid-2", account="u2"),
        ]
        ustore = MagicMock()
        ustore.list_all.return_value = users
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(umo="global-umo", task_key="sp.checkin.all")
        ]
        sstore.list_all_enabled.return_value = [
            _make_schedule(
                umo="session-a",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
            _make_schedule(
                umo="session-a",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u2"}',
            ),
        ]
        estore = MagicMock()
        estore.list_uids.return_value = set()
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(scheduler, "_push_report", new_callable=AsyncMock),
        ):
            mock_checkin.side_effect = lambda user, _semaphore: _make_per_user_result(
                sp_uid=user.sp_uid,
                account=user.account,
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            )
            await scheduler._tick_for_key("global-umo", "sp.checkin.all")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1",
            "uid-2",
        ]
        estore.list_uids.assert_called_once_with("session-a")

    @pytest.mark.asyncio
    async def test_all_mode_includes_uid_when_any_session_participates(self) -> None:
        user = _make_user(sp_uid="uid-1", account="u1")
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(umo="global-umo", task_key="sp.checkin.all")
        ]
        sstore.list_all_enabled.return_value = [
            _make_schedule(
                umo="session-a",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
            _make_schedule(
                umo="session-b",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
        ]
        estore = MagicMock()
        estore.list_uids.side_effect = lambda umo: (
            {"uid-1"} if umo == "session-a" else set()
        )
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_checkin.return_value = _make_per_user_result(sp_uid="uid-1")
            await scheduler._tick_for_key("global-umo", "sp.checkin.all")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1"
        ]
        mock_push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_mode_falls_back_to_all_enabled_users_without_session_subs(
        self,
    ) -> None:
        users = [
            _make_user(sp_uid="uid-1", account="u1"),
            _make_user(sp_uid="uid-2", account="u2"),
        ]
        ustore = MagicMock()
        ustore.list_all.return_value = users
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(umo="umo1", task_key="sp.checkin.all")
        ]
        sstore.list_all_enabled.return_value = [
            _make_schedule(umo="umo1", task_key="sp.checkin.all")
        ]
        estore = MagicMock()
        estore.list_uids.return_value = {"uid-2"}
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_checkin.return_value = _make_per_user_result(sp_uid="uid-1")
            await scheduler._tick_for_key("umo1", "sp.checkin.all")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1"
        ]
        estore.list_uids.assert_called_once_with("umo1")
        mock_push.assert_awaited_once()
        assert mock_push.await_args.args[0] == "umo1"
        assert mock_push.await_args.args[1] == "sp.checkin.all"

    @pytest.mark.asyncio
    async def test_session_mode_skips_excluded_active_uid(self) -> None:
        user = _make_user(sp_uid="uid-1", account="u1")
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(
                umo="umo1",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            )
        ]
        estore = MagicMock()
        estore.list_uids.return_value = {"uid-1"}
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            await scheduler._tick_for_key("umo1", "sp.checkin.session")

        mock_checkin.assert_not_called()
        mock_push.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_mode_pushes_task_key_for_active_uid(self) -> None:
        user = _make_user(sp_uid="uid-1", account="u1")
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        sstore = MagicMock()
        sstore.list_by_umo.return_value = [
            _make_schedule(
                umo="umo1",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            )
        ]
        estore = MagicMock()
        estore.list_uids.return_value = set()
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )

        with (
            patch.object(
                scheduler, "_checkin_user", new_callable=AsyncMock
            ) as mock_checkin,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_checkin.return_value = _make_per_user_result(sp_uid="uid-1")
            await scheduler._tick_for_key("umo1", "sp.checkin.session")

        assert [call.args[0].sp_uid for call in mock_checkin.await_args_list] == [
            "uid-1"
        ]
        estore.list_uids.assert_called_once_with("umo1")
        mock_push.assert_awaited_once()
        assert mock_push.await_args.args[0] == "umo1"
        assert mock_push.await_args.args[1] == "sp.checkin.session"

    @pytest.mark.asyncio
    async def test_concurrent_all_and_session_ticks_share_same_uid_result(
        self,
    ) -> None:
        user = _make_user(sp_uid="uid-1", account="u1")
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        sstore = MagicMock()

        def list_by_umo(umo: str) -> list[ScheduleRow]:
            if umo == "global-umo":
                return [_make_schedule(umo=umo, task_key="sp.checkin.all")]
            if umo == "session-umo":
                return [
                    _make_schedule(
                        umo=umo,
                        task_key="sp.checkin.session",
                        params_json='{"mode":"session","account":"u1"}',
                    )
                ]
            return []

        sstore.list_by_umo.side_effect = list_by_umo
        sstore.list_all_enabled.return_value = [
            _make_schedule(umo="global-umo", task_key="sp.checkin.all"),
            _make_schedule(
                umo="session-umo",
                task_key="sp.checkin.session",
                params_json='{"mode":"session","account":"u1"}',
            ),
        ]
        estore = MagicMock()
        estore.list_uids.return_value = set()
        scheduler = _make_scheduler(
            user_store=ustore,
            schedule_store=sstore,
            exclusion_store=estore,
        )
        scheduler._semaphore = asyncio.Semaphore(2)
        started = asyncio.Event()
        release = asyncio.Event()

        async def do_checkin_once(user_arg: UserRow) -> _PerUserResult:
            started.set()
            await release.wait()
            return _PerUserResult(
                user=user_arg,
                result=TaskResult(status=CheckinStatus.SUCCESS.value, message="OK"),
                skipped=False,
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            )

        with (
            patch.object(
                scheduler, "_do_checkin_both", new_callable=AsyncMock
            ) as mock_do,
            patch.object(
                scheduler, "_push_report", new_callable=AsyncMock
            ) as mock_push,
        ):
            mock_do.side_effect = do_checkin_once
            all_tick = asyncio.create_task(
                scheduler._tick_for_key("global-umo", "sp.checkin.all")
            )
            session_tick = asyncio.create_task(
                scheduler._tick_for_key("session-umo", "sp.checkin.session")
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(all_tick, session_tick)
            finally:
                all_tick.cancel()
                session_tick.cancel()

        assert mock_do.await_count == 1
        assert {call.args[0] for call in mock_push.await_args_list} == {
            "global-umo",
            "session-umo",
        }
        assert {call.args[1] for call in mock_push.await_args_list} == {
            "sp.checkin.all",
            "sp.checkin.session",
        }

    def test_refresh_checkin_jobs_rebuilds_both_checkin_jobs(self) -> None:
        scheduler = _make_scheduler()
        with patch.object(scheduler, "_ensure_job_for") as mock_ensure:
            scheduler.refresh_checkin_jobs("umo1")
        assert [call.args for call in mock_ensure.call_args_list] == [
            ("umo1", "sp.checkin.all"),
            ("umo1", "sp.checkin.session"),
        ]


# ---------------------------------------------------------------------------
# helper 函数
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_is_failed_true(self) -> None:
        r = _make_per_user_result(status=CheckinStatus.FAILED.value)
        assert _is_failed(r)

    def test_is_failed_false(self) -> None:
        r = _make_per_user_result()
        assert not _is_failed(r)


class TestFormatAggregatedReport:
    def test_all_success(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
            _make_per_user_result(
                sp_uid="99999",
                account="u1",
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
        ]
        text, failed = _format_aggregated_report(results, task_key="sp.checkin.all")
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（全局订阅）",
            total=2,
            completed=2,
            daily_line="社区·日签：✅ 2  ⏭️ 0  ❌ 0",
            weekly_line="社区·周签：✅ 2  ⏭️ 0  ❌ 0",
        )
        assert failed == []

    def test_session_title(self) -> None:
        text, failed = _format_aggregated_report(
            [_make_per_user_result()],
            task_key="sp.checkin.session",
        )
        assert text.splitlines()[0] == "South Plus 自动签到（会话订阅）"
        assert failed == []

    def test_unknown_title(self) -> None:
        text, failed = _format_aggregated_report(
            [_make_per_user_result()],
            task_key="sp.checkin.unknown",
        )
        assert text.splitlines()[0] == "South Plus 自动签到"
        assert failed == []

    def test_mixed_with_failure(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                status=CheckinStatus.SUCCESS.value,
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
            _make_per_user_result(
                sp_uid="99999",
                account="u1",
                status=CheckinStatus.FAILED.value,
                daily_status=CheckinStatus.FAILED.value,
                weekly_status=CheckinStatus.FAILED.value,
            ),
        ]
        text, failed = _format_aggregated_report(
            results,
            task_key="sp.checkin.session",
        )
        _assert_subscription_report_lines(
            text,
            title="South Plus 自动签到（会话订阅）",
            total=2,
            completed=1,
            daily_line="社区·日签：✅ 1  ⏭️ 0  ❌ 1",
            weekly_line="社区·周签：✅ 1  ⏭️ 0  ❌ 1",
        )
        assert len(failed) == 1
        assert failed[0].user.sp_uid == "99999"

    def test_already_done_counts_as_skip(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                skipped=True,
                daily_status=CheckinStatus.ALREADY_DONE.value,
                weekly_status=CheckinStatus.ALREADY_DONE.value,
            ),
        ]
        text, failed = _format_aggregated_report(results)
        assert "南+账号：1 个" in text
        assert "完成 1：✅ 成功 1" in text
        assert "社区·日签：✅ 0  ⏭️ 1  ❌ 0" in text
        assert "社区·周签：✅ 0  ⏭️ 1  ❌ 0" in text
        assert failed == []

    def test_no_failure_no_mention(self) -> None:
        """全部成功时不应出现「失败」字样。"""
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
        ]
        text, failed = _format_aggregated_report(results)
        assert "完成 1：✅ 成功 1" in text
        assert "❌ 0" in text
        assert failed == []

    def test_daily_fail_weekly_ok(self) -> None:
        """日签失败周签成功时，日签行有失败计数，周签行没有。"""
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="qq123",
                status=CheckinStatus.FAILED.value,
                daily_status=CheckinStatus.FAILED.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
        ]
        text, failed = _format_aggregated_report(results)
        lines = text.splitlines()
        daily_line = next(ln for ln in lines if ln.startswith("社区·日签"))
        weekly_line = next(ln for ln in lines if ln.startswith("社区·周签"))
        assert daily_line == "社区·日签：✅ 0  ⏭️ 0  ❌ 1"
        assert weekly_line == "社区·周签：✅ 1  ⏭️ 0  ❌ 0"
        assert "完成 0：✅ 成功 0" in text
        assert len(failed) == 1
        assert failed[0].user.account == "qq123"


class TestFormatGlobalReport:
    def test_empty(self) -> None:
        text = _format_global_report([])
        assert text.splitlines() == [
            "South Plus 主动签到（全体账号）",
            "南+账号：0 个",
            "完成 0：✅ 成功 0",
            "社区·日签：✅ 0  ⏭️ 请勿重复签到 0  ❌ 0",
            "社区·周签：✅ 0  ⏭️ 请勿重复签到 0  ❌ 0",
        ]

    def test_all_success(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
            _make_per_user_result(
                sp_uid="99999",
                account="u2",
                daily_status=CheckinStatus.SUCCESS.value,
                weekly_status=CheckinStatus.SUCCESS.value,
            ),
        ]
        text = _format_global_report(results)
        assert text.splitlines() == [
            "South Plus 主动签到（全体账号）",
            "南+账号：2 个",
            "完成 2：✅ 成功 2",
            "社区·日签：✅ 2  ⏭️ 请勿重复签到 0  ❌ 0",
            "社区·周签：✅ 2  ⏭️ 请勿重复签到 0  ❌ 0",
        ]

    def test_skipped_counts_as_completed(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                skipped=True,
                daily_status=CheckinStatus.ALREADY_DONE.value,
                weekly_status=CheckinStatus.ALREADY_DONE.value,
            ),
        ]
        text = _format_global_report(results)
        assert "完成 1：✅ 成功 1" in text
        assert "社区·日签：✅ 0  ⏭️ 请勿重复签到 1  ❌ 0" in text
        assert "社区·周签：✅ 0  ⏭️ 请勿重复签到 1  ❌ 0" in text

    def test_with_failures(self) -> None:
        results = [
            _make_per_user_result(
                sp_uid="10001",
                account="u1",
                status=CheckinStatus.FAILED.value,
                daily_status=CheckinStatus.FAILED.value,
                weekly_status=CheckinStatus.FAILED.value,
            ),
        ]
        text = _format_global_report(results)
        assert "完成 0：✅ 成功 0" in text
        assert "社区·日签：✅ 0  ⏭️ 请勿重复签到 0  ❌ 1" in text
        assert "社区·周签：✅ 0  ⏭️ 请勿重复签到 0  ❌ 1" in text
