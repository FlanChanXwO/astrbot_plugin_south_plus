"""``checkin_record`` 表持久化层。

每任务每期一行，保留全部签到历史。用 ``(sp_uid, task_key, period_key)``
唯一约束保护幂等；``is_already_done`` 搬入 cache 判定逻辑。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Literal

from ..datamodels import CheckinRow
from ._connection import connect as _db_connect

_STALE_SUCCESS_MARKERS = ("未申请", "请赶紧", "去完成")
GenuineCheckinStatus = Literal["success", "already_done"]


class CheckinStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkin_record (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    sp_uid       TEXT NOT NULL REFERENCES "user"(sp_uid),
                    task_key     TEXT NOT NULL,
                    period_key   TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    message      TEXT NOT NULL DEFAULT '',
                    error        TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    UNIQUE(sp_uid, task_key, period_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkin_lookup "
                "ON checkin_record(sp_uid, task_key, period_key)"
            )
            conn.commit()

    def record(
        self,
        *,
        sp_uid: str,
        task_key: str,
        period_key: str,
        status: str,
        message: str = "",
        error: str = "",
    ) -> None:
        """写入一条签到记录。重复写入同名期时按 UNIQUE 约束覆盖。"""
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO checkin_record (sp_uid, task_key, period_key, status, message, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sp_uid, task_key, period_key) DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message,
                    error = excluded.error
                """,
                (sp_uid, task_key, period_key, status, message, error, stamp),
            )
            conn.commit()

    def get_for_period(
        self, *, sp_uid: str, task_key: str, period_key: str
    ) -> CheckinRow | None:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM checkin_record WHERE sp_uid = ? AND task_key = ? AND period_key = ?",
                (sp_uid, task_key, period_key),
            ).fetchone()
        return _row_to_checkin(row) if row else None

    def is_already_done(self, *, sp_uid: str, task_key: str, period_key: str) -> bool:
        """该期是否已经可信地完成——缓存跳过判断。"""
        return bool(
            self.get_genuine_status(
                sp_uid=sp_uid, task_key=task_key, period_key=period_key
            )
        )

    def get_genuine_status(
        self, *, sp_uid: str, task_key: str, period_key: str
    ) -> GenuineCheckinStatus | None:
        """返回可信缓存状态；None 表示无缓存或缓存不可信。"""
        row = self.get_for_period(
            sp_uid=sp_uid, task_key=task_key, period_key=period_key
        )
        if row is None:
            return None
        return _genuine_cache_status(row.status, row.message)

    def history(
        self, *, sp_uid: str, task_key: str, limit: int = 50
    ) -> list[CheckinRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM checkin_record WHERE sp_uid = ? AND task_key = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (sp_uid, task_key, limit),
            ).fetchall()
        return [_row_to_checkin(r) for r in rows]

    def list_recent(
        self,
        *,
        sp_uid: str = "",
        task_key: str = "",
        status: str = "",
        period_key: str = "",
        limit: int = 100,
    ) -> list[CheckinRow]:
        """按可选条件列出最近签到历史，供 Dashboard 排障查看。"""
        clauses: list[str] = []
        params: list[str | int] = []
        if sp_uid:
            clauses.append("sp_uid = ?")
            params.append(sp_uid)
        if task_key:
            clauses.append("task_key = ?")
            params.append(task_key)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if period_key:
            clauses.append("period_key = ?")
            params.append(period_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit or 100)))
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM checkin_record {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_row_to_checkin(r) for r in rows]


def _genuine_cache_status(status: str, message: str) -> GenuineCheckinStatus | None:
    """保留可信缓存的原始分类，用于报告层区分成功与跳过。"""
    if status == "already_done":
        return status
    if status != "success":
        return None
    if any(marker in message for marker in _STALE_SUCCESS_MARKERS):
        return None
    return status


def _row_to_checkin(row: sqlite3.Row) -> CheckinRow:
    return CheckinRow(
        id=row["id"],
        sp_uid=row["sp_uid"],
        task_key=row["task_key"],
        period_key=row["period_key"],
        status=row["status"],
        message=row["message"],
        error=row["error"],
        created_at=row["created_at"],
    )


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
