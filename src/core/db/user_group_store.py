"""``user_group`` 表持久化层。

M:N 关联：记录用户在哪个群被观测到（消息心跳驱动）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from ._connection import connect as _db_connect


class UserGroupStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_group (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    sp_uid       TEXT NOT NULL REFERENCES "user"(sp_uid),
                    group_id     INTEGER NOT NULL REFERENCES "group"(id),
                    last_seen_at TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    UNIQUE(sp_uid, group_id)
                )
                """
            )
            conn.commit()

    def upsert(self, *, sp_uid: str, group_id: int) -> None:
        """插入或刷新心跳时间。"""
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_group (sp_uid, group_id, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sp_uid, group_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (sp_uid, group_id, stamp, stamp, stamp),
            )
            conn.commit()

    def get_groups_for_user(self, sp_uid: str) -> list[int]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT group_id FROM user_group WHERE sp_uid = ?", (sp_uid,)
            ).fetchall()
        return [row["group_id"] for row in rows]

    def get_users_in_group(self, group_id: int) -> list[str]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT sp_uid FROM user_group WHERE group_id = ?", (group_id,)
            ).fetchall()
        return [row["sp_uid"] for row in rows]

    def delete_by_user(self, sp_uid: str) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_group WHERE sp_uid = ?", (sp_uid,))
            conn.commit()

    def delete_stale(self, keep_uids: set[str]) -> int:
        if not keep_uids:
            with self._lock, _db_connect(self.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM user_group").fetchone()[0]
                conn.execute("DELETE FROM user_group")
                conn.commit()
                return count

        placeholders = ",".join("?" * len(keep_uids))
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM user_group WHERE sp_uid NOT IN ({placeholders})",
                tuple(keep_uids),
            )
            conn.commit()
            return cursor.rowcount


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
