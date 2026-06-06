"""``schedule`` 表持久化层。

持久化订阅记录，bot 重启后可恢复。锁仅用于 ``batch_update_cron`` 路径，
subscribe / unsubscribe 不加锁。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..datamodels import ScheduleRow
from ._connection import connect as _db_connect


class ScheduleStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._cron_lock = threading.Lock()
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    umo          TEXT NOT NULL,
                    task_key     TEXT NOT NULL,
                    cron         TEXT NOT NULL,
                    params_json  TEXT NOT NULL DEFAULT '{}',
                    enabled      INTEGER NOT NULL DEFAULT 1,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(umo, task_key, params_json)
                )
                """
            )
            conn.commit()

    def subscribe(
        self, *, umo: str, task_key: str, cron: str, params_json: str = "{}"
    ) -> ScheduleRow:
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schedule (umo, task_key, cron, params_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(umo, task_key, params_json) DO UPDATE SET
                    cron = excluded.cron,
                    enabled = 1,
                    updated_at = excluded.updated_at
                """,
                (umo, task_key, cron, params_json, stamp, stamp),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM schedule WHERE umo = ? AND task_key = ? AND params_json = ?",
                (umo, task_key, params_json),
            ).fetchone()
        return _row_to_schedule(row)

    def unsubscribe(self, *, umo: str, task_key: str, params_json: str = "{}") -> bool:
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM schedule WHERE umo = ? AND task_key = ? AND params_json = ?",
                (umo, task_key, params_json),
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_subscribed(
        self, *, umo: str, task_key: str, params_json: str = "{}"
    ) -> bool:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM schedule WHERE umo = ? AND task_key = ? AND params_json = ? AND enabled = 1",
                (umo, task_key, params_json),
            ).fetchone()
        return row is not None

    def list_by_umo(self, umo: str) -> list[ScheduleRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM schedule WHERE umo = ? ORDER BY created_at DESC",
                (umo,),
            ).fetchall()
        return [_row_to_schedule(r) for r in rows]

    def list_all_enabled(self) -> list[ScheduleRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM schedule WHERE enabled = 1 ORDER BY created_at"
            ).fetchall()
        return [_row_to_schedule(r) for r in rows]

    def list_all(self) -> list[ScheduleRow]:
        """列出全部调度订阅，供管理面查看与筛选。"""
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM schedule ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [_row_to_schedule(r) for r in rows]

    def get_by_id(self, id: int) -> ScheduleRow | None:
        """按主键读取调度订阅。"""
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM schedule WHERE id = ?", (id,)).fetchone()
        return _row_to_schedule(row) if row else None

    def set_enabled(self, id: int, enabled: bool) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                "UPDATE schedule SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _stamp(), id),
            )
            conn.commit()

    def delete_by_id(self, id: int) -> bool:
        """按主键删除调度订阅。返回 True 表示确有行被删除。"""
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM schedule WHERE id = ?", (id,))
            conn.commit()
        return cursor.rowcount > 0

    def batch_update_cron(self, *, task_key_prefix: str, new_cron: str) -> list[str]:
        """更新所有匹配前缀的订阅 cron。返回受影响的 umo 列表。
        仅在锁下执行——全局只有一个线程能走此路径。
        """
        with self._cron_lock:
            with self._lock, _db_connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT umo FROM schedule WHERE task_key LIKE ? AND enabled = 1",
                    (task_key_prefix + "%",),
                ).fetchall()
                affected = [row["umo"] for row in rows]

                conn.execute(
                    "UPDATE schedule SET cron = ?, updated_at = ? WHERE task_key LIKE ?",
                    (new_cron, _stamp(), task_key_prefix + "%"),
                )
                conn.commit()
        return affected


def _row_to_schedule(row: sqlite3.Row) -> ScheduleRow:
    return ScheduleRow(
        id=row["id"],
        umo=row["umo"],
        task_key=row["task_key"],
        cron=row["cron"],
        params_json=row["params_json"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
