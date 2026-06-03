"""``CheckinStore`` 持久化测试。"""

from __future__ import annotations

from pathlib import Path

from src.core.data_source import CheckinStore


def test_initial_get_returns_none(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    assert store.get("2030219") is None


def test_upsert_daily_then_weekly_independent(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.upsert_daily(
        "2030219",
        date="2026-06-03",
        status="success",
        message="日签：完成",
        error="",
    )
    rec = store.get("2030219")
    assert rec is not None
    assert rec.last_daily_date == "2026-06-03"
    assert rec.last_daily_status == "success"
    assert rec.last_daily_message == "日签：完成"
    # 周字段还未写入，保持空串。
    assert rec.last_weekly_date == ""
    assert rec.last_weekly_status == ""

    store.upsert_weekly(
        "2030219",
        date="2026-W23",
        status="failed",
        message="周签：失败",
        error="任务条件未满足",
    )
    rec = store.get("2030219")
    assert rec is not None
    assert rec.last_daily_status == "success"  # 日字段没被覆盖
    assert rec.last_weekly_status == "failed"
    assert rec.last_weekly_error == "任务条件未满足"


def test_upsert_overwrites_existing_dimension(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.upsert_daily(
        "uid",
        date="2026-06-01",
        status="success",
        message="ok",
        error="",
    )
    store.upsert_daily(
        "uid",
        date="2026-06-03",
        status="already_done",
        message="今天已经完成",
        error="",
    )
    rec = store.get("uid")
    assert rec is not None
    assert rec.last_daily_date == "2026-06-03"
    assert rec.last_daily_status == "already_done"
    assert rec.last_daily_message == "今天已经完成"


def test_multiple_uids_are_independent(tmp_path: Path) -> None:
    store = CheckinStore(tmp_path / "southplus.db")
    store.upsert_daily("a", date="2026-06-03", status="success", message="A", error="")
    store.upsert_daily(
        "b", date="2026-06-03", status="failed", message="B", error="oops"
    )
    a = store.get("a")
    b = store.get("b")
    assert a is not None and b is not None
    assert a.last_daily_message == "A"
    assert b.last_daily_message == "B"
    assert b.last_daily_error == "oops"
