"""新 ``CheckinScheduler`` 测试。

覆盖：生命周期、订阅管理、全量签到、helper 函数。
"""

from __future__ import annotations

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
from src.southplus.models import CheckinStatus


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

    @pytest.mark.asyncio
    async def test_single_account_success(self) -> None:
        user = _make_user()
        ustore = MagicMock()
        ustore.list_all.return_value = [user]
        cstore = MagicMock()
        cstore.is_already_done.return_value = False

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
        assert "日签" in text
        assert "周签" in text


class TestSessionExclusion:
    @pytest.mark.asyncio
    async def test_all_mode_skips_excluded_uid_for_current_session(self) -> None:
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
        text, failed = _format_aggregated_report(results)
        assert "日签" in text
        assert "周签" in text
        assert "成功 2" in text
        assert "失败" not in text
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
        text, failed = _format_aggregated_report(results)
        assert "失败 1" in text
        assert len(failed) == 1
        assert failed[0].user.sp_uid == "99999"

    def test_skipped_count(self) -> None:
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
        assert "跳过 1" in text
        assert "失败" not in text
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
        assert "失败" not in text
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
        lines = text.split("\n")
        daily_line = next(ln for ln in lines if ln.startswith("日签"))
        weekly_line = next(ln for ln in lines if ln.startswith("周签"))
        assert "失败" in daily_line
        assert "失败" not in weekly_line
        assert len(failed) == 1
        assert failed[0].user.account == "qq123"


class TestFormatGlobalReport:
    def test_empty(self) -> None:
        text = _format_global_report([])
        assert "总账号数：0" in text

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
        assert "总账号数：2" in text
        assert "日签" in text
        assert "周签" in text
        assert "成功 2" in text
        assert "失败" not in text

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
        assert "失败 1" in text
