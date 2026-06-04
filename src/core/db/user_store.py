"""``user`` 表持久化层。
约束：

* 每个南+ UID 全局唯一（``sp_uid`` PK）。
* 同一个 ``(account, platform)`` 可以绑定多个 UID；最多一个 ``is_active = 1``。
* Cookie 以明文写入 SQLite。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..datamodels import AddAccountResult, AddAccountStatus, UserRow
from ._connection import connect as _db_connect


class UserStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._lock, _db_connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS "user" (
                    sp_uid       TEXT PRIMARY KEY,
                    account      TEXT NOT NULL,
                    platform     TEXT NOT NULL,
                    cookie       TEXT NOT NULL DEFAULT '',
                    is_active    INTEGER NOT NULL DEFAULT 0,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_account_platform "
                'ON "user"(account, platform)'
            )
            conn.commit()

    # ------------------------------------------------------------------
    # 绑定 / 刷新
    # ------------------------------------------------------------------

    def add_or_update(
        self,
        *,
        sp_uid: str,
        account: str,
        platform: str,
        cookie: str,
    ) -> AddAccountResult:
        """登录成功后调用。

        * UID 不存在 → INSERT，置为当前用户激活。``CREATED``。
        * UID 已存在且属于同一 ``(account, platform)`` → UPDATE cookie，设为激活。``REFRESHED``。
        * UID 已存在且属于另一个 ``account`` → 不动数据，返回占用者行。``OWNED_BY_OTHER``。
        """

        if not sp_uid:
            raise ValueError("sp_uid 不能为空")
        stamp = _stamp()
        with self._lock, _db_connect(self.db_path) as conn:
            existing = conn.execute(
                'SELECT * FROM "user" WHERE sp_uid = ?', (sp_uid,)
            ).fetchone()
            if existing is not None and existing["account"] != account:
                return AddAccountResult(
                    status=AddAccountStatus.OWNED_BY_OTHER,
                    account=self._row_to_user(existing),
                )

            if existing is None:
                conn.execute(
                    'UPDATE "user" SET is_active = 0 WHERE account = ? AND platform = ?',
                    (account, platform),
                )
                conn.execute(
                    """
                    INSERT INTO "user" (sp_uid, account, platform, cookie, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (sp_uid, account, platform, cookie, stamp, stamp),
                )
                status = "created"
            else:
                conn.execute(
                    'UPDATE "user" SET is_active = 0 WHERE account = ? AND platform = ?',
                    (account, platform),
                )
                conn.execute(
                    """
                    UPDATE "user"
                    SET cookie = ?, is_active = 1, updated_at = ?
                    WHERE sp_uid = ?
                    """,
                    (cookie, stamp, sp_uid),
                )
                status = "refreshed"

            conn.commit()
            row = conn.execute(
                'SELECT * FROM "user" WHERE sp_uid = ?', (sp_uid,)
            ).fetchone()

        return AddAccountResult(
            status=AddAccountStatus(status),
            account=self._row_to_user(row),
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_active(self, account: str, platform: str) -> UserRow | None:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT * FROM "user" WHERE account = ? AND platform = ? AND is_active = 1',
                (account, platform),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_uid(self, sp_uid: str) -> UserRow | None:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT * FROM "user" WHERE sp_uid = ?', (sp_uid,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def list_for_account(self, account: str, platform: str) -> list[UserRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT * FROM "user" WHERE account = ? AND platform = ? '
                "ORDER BY is_active DESC, updated_at DESC",
                (account, platform),
            ).fetchall()
        return [self._row_to_user(row) for row in rows]

    def list_all(self) -> list[UserRow]:
        with self._lock, _db_connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT * FROM "user" ORDER BY updated_at DESC'
            ).fetchall()
        return [self._row_to_user(row) for row in rows]

    # ------------------------------------------------------------------
    # 切换 / 删除
    # ------------------------------------------------------------------

    def switch_active(self, account: str, platform: str, sp_uid: str) -> bool:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT account FROM "user" WHERE sp_uid = ?', (sp_uid,)
            ).fetchone()
            if row is None or row["account"] != account:
                return False
            conn.execute(
                'UPDATE "user" SET is_active = 0 WHERE account = ? AND platform = ?',
                (account, platform),
            )
            conn.execute(
                'UPDATE "user" SET is_active = 1, updated_at = ? WHERE sp_uid = ?',
                (_stamp(), sp_uid),
            )
            conn.commit()
        return True

    def delete_account(self, account: str, sp_uid: str) -> bool:
        with self._lock, _db_connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT account, is_active FROM "user" WHERE sp_uid = ?',
                (sp_uid,),
            ).fetchone()
            if row is None or row["account"] != account:
                return False
            conn.execute('DELETE FROM "user" WHERE sp_uid = ?', (sp_uid,))
            if row["is_active"]:
                fallback = conn.execute(
                    'SELECT sp_uid FROM "user" WHERE account = ? '
                    "ORDER BY updated_at DESC LIMIT 1",
                    (account,),
                ).fetchone()
                if fallback is not None:
                    conn.execute(
                        'UPDATE "user" SET is_active = 1, updated_at = ? WHERE sp_uid = ?',
                        (_stamp(), fallback["sp_uid"]),
                    )
            conn.commit()
        return True

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def delete_stale(self, keep_uids: set[str]) -> int:
        """删除不在 ``keep_uids`` 中的 user 行。返回删除行数。"""
        if not keep_uids:
            with self._lock, _db_connect(self.db_path) as conn:
                count = conn.execute('SELECT COUNT(*) FROM "user"').fetchone()[0]
                conn.execute('DELETE FROM "user"')
                conn.commit()
                return count

        placeholders = ",".join("?" * len(keep_uids))
        with self._lock, _db_connect(self.db_path) as conn:
            cursor = conn.execute(
                f'DELETE FROM "user" WHERE sp_uid NOT IN ({placeholders})',
                tuple(keep_uids),
            )
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # 行转模型
    # ------------------------------------------------------------------

    def _row_to_user(self, row: sqlite3.Row) -> UserRow:
        return UserRow(
            sp_uid=row["sp_uid"],
            account=row["account"],
            platform=row["platform"],
            cookie=row["cookie"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _stamp() -> str:
    from ...utils import now_iso

    return now_iso()
