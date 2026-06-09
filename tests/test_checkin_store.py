"""新 ``CheckinStore`` 持久化测试。"""

from __future__ import annotations

from pathlib import Path

from src.core.db.checkin_store import CheckinStore


def test_initial_is_already_done_returns_false(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    assert not store.is_already_done(
        sp_uid="2030219",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )


def test_record_then_is_already_done(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="2030219",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="日签：完成",
        error="",
    )
    assert store.is_already_done(
        sp_uid="2030219",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )


def test_daily_and_weekly_independent(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="OK",
        error="",
    )
    assert store.is_already_done(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )
    assert not store.is_already_done(
        sp_uid="uid1",
        task_key="sp.checkin.weekly",
        period_key="2026-W23",
    )


def test_upsert_overwrites_existing(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="OK",
        error="",
    )
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="already_done",
        message="重试",
        error="",
    )
    row = store.get_for_period(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )
    assert row is not None
    assert row.status == "already_done"
    assert row.message == "重试"


def test_multiple_uids_independent(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="a",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="A",
        error="",
    )
    store.record(
        sp_uid="b",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="failed",
        message="B",
        error="oops",
    )
    assert store.is_already_done(
        sp_uid="a",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )
    b_row = store.get_for_period(
        sp_uid="b",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )
    assert b_row is not None
    assert b_row.status == "failed"
    assert b_row.error == "oops"


def test_history_returns_latest_first(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    for i in range(3):
        store.record(
            sp_uid="uid1",
            task_key="sp.checkin.daily",
            period_key=f"2026-06-0{i + 1}",
            status="success",
            message=str(i),
            error="",
        )
    history = store.history(sp_uid="uid1", task_key="sp.checkin.daily", limit=50)
    assert len(history) == 3
    assert history[0].period_key == "2026-06-03"


def test_history_limit(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    for i in range(5):
        store.record(
            sp_uid="uid1",
            task_key="sp.checkin.daily",
            period_key=f"2026-06-0{i + 1}",
            status="success",
            message=str(i),
            error="",
        )
    assert len(store.history(sp_uid="uid1", task_key="sp.checkin.daily", limit=2)) == 2


def test_already_done_cache_logic(tmp_path: Path) -> None:
    """success 状态 + 干净消息 → genuine; 旧版脏文案 → 不信任。"""
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="完成",
        error="",
    )
    assert store.is_already_done(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )
    # 旧版 success 带脏文案（"未申请"）不应被信任。
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="未申请任务",
        error="",
    )
    # record 是 upsert，所以会覆盖。测试脏文案被正确过滤。
    assert not store.is_already_done(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
    )


def test_genuine_status_preserves_success_and_already_done(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.record(
        sp_uid="uid1",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="日签：完成[日常]任务,获得奖励",
        error="",
    )
    assert (
        store.get_genuine_status(
            sp_uid="uid1",
            task_key="sp.checkin.daily",
            period_key="2026-06-04",
        )
        == "success"
    )

    store.record(
        sp_uid="uid2",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="already_done",
        message="日签：已签到，请勿重复签到。",
        error="",
    )
    assert (
        store.get_genuine_status(
            sp_uid="uid2",
            task_key="sp.checkin.daily",
            period_key="2026-06-04",
        )
        == "already_done"
    )

    store.record(
        sp_uid="uid3",
        task_key="sp.checkin.daily",
        period_key="2026-06-04",
        status="success",
        message="未申请任务",
        error="",
    )
    assert (
        store.get_genuine_status(
            sp_uid="uid3",
            task_key="sp.checkin.daily",
            period_key="2026-06-04",
        )
        is None
    )
