"""``group`` 表持久化层。

记录 bot 当前服务的群目录，供清理等管理操作使用。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..datamodels import GroupRow
from ._connection import connect as _db_connect


class GroupStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS "group" (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id       TEXT NOT NULL,
                    platform     TEXT NOT NULL,
                    group_id     TEXT NOT NULL,
                    group_name   TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(platform, group_id)
                )
                """
            )
            conn.commit()

    def upsert(
        self, *, bot_id: str, platform: str, group_id: str, group_name: str = ""
    ) -> int:
        """插入或更新群记录，返回 row id。"""
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO "group" (bot_id, platform, group_id, group_name, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, group_id) DO UPDATE SET
                    group_name = excluded.group_name,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (bot_id, platform, group_id, group_name, stamp, stamp, stamp),
            )
            conn.commit()
            row = conn.execute(
                'SELECT id FROM "group" WHERE platform = ? AND group_id = ?',
                (platform, group_id),
            ).fetchone()
        return row["id"]

    def list_all(self) -> list[GroupRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT * FROM "group" ORDER BY last_seen_at DESC'
            ).fetchall()
        return [_row_to_group(row) for row in rows]

    def get_by_id(self, group_id: int) -> GroupRow | None:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT * FROM "group" WHERE id = ?', (group_id,)
            ).fetchone()
        return _row_to_group(row) if row else None

    def delete_stale(self, keep_ids: set[int]) -> int:
        if not keep_ids:
            with self._lock, _db_connect(self.db_path) as conn:
                count = conn.execute('SELECT COUNT(*) FROM "group"').fetchone()[0]
                conn.execute('DELETE FROM "group"')
                conn.commit()
                return count

        placeholders = ",".join("?" * len(keep_ids))
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute(
                f'DELETE FROM "group" WHERE id NOT IN ({placeholders})',
                tuple(keep_ids),
            )
            conn.commit()
            return cursor.rowcount


def _row_to_group(row: sqlite3.Row) -> GroupRow:
    return GroupRow(
        id=row["id"],
        bot_id=row["bot_id"],
        platform=row["platform"],
        group_id=row["group_id"],
        group_name=row["group_name"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
