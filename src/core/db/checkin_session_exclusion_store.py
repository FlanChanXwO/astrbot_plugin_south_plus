"""``checkin_session_exclusion`` 表持久化层。

记录 Dashboard 对某个会话 ``umo`` 的自动签到排除关系。该关系是会话级，
不会改变账号全局 ``auto_checkin`` 开关。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..datamodels import CheckinSessionExclusionRow
from ._connection import connect as _db_connect


class CheckinSessionExclusionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkin_session_exclusion (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    umo          TEXT NOT NULL,
                    sp_uid       TEXT NOT NULL REFERENCES "user"(sp_uid),
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(umo, sp_uid)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkin_session_exclusion_umo "
                "ON checkin_session_exclusion(umo)"
            )
            conn.commit()

    def exclude(self, *, umo: str, sp_uid: str) -> CheckinSessionExclusionRow:
        if not umo or not sp_uid:
            raise ValueError("umo 与 sp_uid 不能为空")
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO checkin_session_exclusion (umo, sp_uid, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(umo, sp_uid) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (umo, sp_uid, stamp, stamp),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM checkin_session_exclusion WHERE umo = ? AND sp_uid = ?",
                (umo, sp_uid),
            ).fetchone()
        return _row_to_exclusion(row)

    def restore(self, *, umo: str, sp_uid: str) -> bool:
        if not umo or not sp_uid:
            return False
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM checkin_session_exclusion WHERE umo = ? AND sp_uid = ?",
                (umo, sp_uid),
            )
            conn.commit()
        return cursor.rowcount > 0

    def is_excluded(self, *, umo: str, sp_uid: str) -> bool:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM checkin_session_exclusion WHERE umo = ? AND sp_uid = ?",
                (umo, sp_uid),
            ).fetchone()
        return row is not None

    def list_uids(self, umo: str) -> set[str]:
        if not umo:
            return set()
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT sp_uid FROM checkin_session_exclusion WHERE umo = ?",
                (umo,),
            ).fetchall()
        return {row["sp_uid"] for row in rows}

    def list_by_umo(self, umo: str) -> list[CheckinSessionExclusionRow]:
        if not umo:
            return []
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM checkin_session_exclusion "
                "WHERE umo = ? ORDER BY updated_at DESC, id DESC",
                (umo,),
            ).fetchall()
        return [_row_to_exclusion(row) for row in rows]


def _row_to_exclusion(row: sqlite3.Row) -> CheckinSessionExclusionRow:
    return CheckinSessionExclusionRow(
        id=row["id"],
        umo=row["umo"],
        sp_uid=row["sp_uid"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
