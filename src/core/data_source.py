"""SQLite 持久化层：聊天用户 -> South Plus 账号的多对多绑定。

约束：

* 每个南+ UID 在数据库里全局只能被一个 ``user_key`` 绑定（uid PK）。
* 同一个 ``user_key`` 可以绑定多个 UID；任何时刻最多一个 ``is_active = 1``。
* Cookie 通过 ``utils.crypto`` 透明加解密（key 留空时退化明文，仅本机调试）。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..utils import decrypt_secret, encrypt_secret, now_iso
from .datamodels import (
    AddAccountResult,
    AddAccountStatus,
    CheckinRecord,
    StoredAccount,
)
from .logger import plugin_logger


class AccountStore:
    def __init__(self, db_path: Path, *, cookie_encryption_key: str = "") -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cookie_key = cookie_encryption_key
        self._lock = threading.RLock()
        self._init_db()
        if not cookie_encryption_key:
            plugin_logger.warning(
                "cookie_encryption_key 未配置，Cookie 将以明文写入 SQLite，仅适用于本机调试。"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    uid TEXT PRIMARY KEY,
                    user_key TEXT NOT NULL,
                    unified_msg_origin TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    cookie TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT NOT NULL DEFAULT '',
                    last_message TEXT NOT NULL DEFAULT '',
                    last_run_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_accounts_user_key ON accounts(user_key)"
            )
            conn.commit()

    # --- 绑定 / 刷新 -------------------------------------------------------

    def add_or_update(
        self,
        *,
        uid: str,
        user_key: str,
        unified_msg_origin: str,
        username: str,
        cookie: str,
    ) -> AddAccountResult:
        """登录成功后调用。按 UID 唯一性决定走哪个分支：

        * UID 不存在 -> 插入，置为当前用户的激活账号。``CREATED``。
        * UID 已存在且属于同一个 ``user_key`` -> 更新 cookie/username 并把它
          设为激活账号。``REFRESHED``。
        * UID 已存在且属于另一个 ``user_key`` -> 不动数据库，原样返回占用
          者的行。``OWNED_BY_OTHER``。
        """

        if not uid:
            raise ValueError("uid 不能为空")
        encrypted_cookie = encrypt_secret(cookie, self._cookie_key) if cookie else ""
        stamp = now_iso()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM accounts WHERE uid = ?", (uid,)
            ).fetchone()
            if existing is not None and existing["user_key"] != user_key:
                return AddAccountResult(
                    status=AddAccountStatus.OWNED_BY_OTHER,
                    account=self._row_to_account(existing),
                )

            if existing is None:
                conn.execute(
                    "UPDATE accounts SET is_active = 0 WHERE user_key = ?",
                    (user_key,),
                )
                conn.execute(
                    """
                    INSERT INTO accounts (
                        uid, user_key, unified_msg_origin, username, cookie,
                        is_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        uid,
                        user_key,
                        unified_msg_origin,
                        username,
                        encrypted_cookie,
                        stamp,
                        stamp,
                    ),
                )
                status = AddAccountStatus.CREATED
            else:
                conn.execute(
                    "UPDATE accounts SET is_active = 0 WHERE user_key = ?",
                    (user_key,),
                )
                conn.execute(
                    """
                    UPDATE accounts SET
                        unified_msg_origin = ?,
                        username = ?,
                        cookie = ?,
                        is_active = 1,
                        updated_at = ?
                    WHERE uid = ?
                    """,
                    (
                        unified_msg_origin,
                        username,
                        encrypted_cookie,
                        stamp,
                        uid,
                    ),
                )
                status = AddAccountStatus.REFRESHED
            conn.commit()

            row = conn.execute(
                "SELECT * FROM accounts WHERE uid = ?", (uid,)
            ).fetchone()
        return AddAccountResult(status=status, account=self._row_to_account(row))

    # --- 查询 -------------------------------------------------------------

    def get_active(self, user_key: str) -> StoredAccount | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE user_key = ? AND is_active = 1",
                (user_key,),
            ).fetchone()
        return self._row_to_account(row) if row else None

    def get_by_uid(self, uid: str) -> StoredAccount | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE uid = ?",
                (uid,),
            ).fetchone()
        return self._row_to_account(row) if row else None

    def list_for_user(self, user_key: str) -> list[StoredAccount]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE user_key = ? ORDER BY is_active DESC, updated_at DESC",
                (user_key,),
            ).fetchall()
        return [self._row_to_account(row) for row in rows]

    def list_all(self) -> list[StoredAccount]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY updated_at DESC",
            ).fetchall()
        return [self._row_to_account(row) for row in rows]

    # --- 切换 / 删除 -------------------------------------------------------

    def switch_active(self, user_key: str, uid: str) -> bool:
        """把 ``uid`` 设为 ``user_key`` 的激活账号。``uid`` 必须属于该用户。

        返回 ``True`` 表示切换成功；``False`` 表示该 ``user_key`` 没有这条
        绑定（uid 不存在或被别人占用）。
        """

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_key FROM accounts WHERE uid = ?",
                (uid,),
            ).fetchone()
            if row is None or row["user_key"] != user_key:
                return False
            conn.execute(
                "UPDATE accounts SET is_active = 0 WHERE user_key = ?",
                (user_key,),
            )
            conn.execute(
                "UPDATE accounts SET is_active = 1, updated_at = ? WHERE uid = ?",
                (now_iso(), uid),
            )
            conn.commit()
        return True

    def delete_account(self, user_key: str, uid: str) -> bool:
        """删除属于 ``user_key`` 的某条绑定。返回 ``True`` 表示删除成功。"""

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_key, is_active FROM accounts WHERE uid = ?",
                (uid,),
            ).fetchone()
            if row is None or row["user_key"] != user_key:
                return False
            conn.execute("DELETE FROM accounts WHERE uid = ?", (uid,))
            # 若被删的是激活账号，自动把该用户最新一条设回激活。
            if row["is_active"]:
                fallback = conn.execute(
                    "SELECT uid FROM accounts WHERE user_key = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (user_key,),
                ).fetchone()
                if fallback is not None:
                    conn.execute(
                        "UPDATE accounts SET is_active = 1, updated_at = ? WHERE uid = ?",
                        (now_iso(), fallback["uid"]),
                    )
            conn.commit()
        return True

    # --- 运行结果 ---------------------------------------------------------

    def update_run_result(self, uid: str, *, status: str, message: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET last_status = ?, last_message = ?, last_run_at = ?, updated_at = ?
                WHERE uid = ?
                """,
                (status, message, now_iso(), now_iso(), uid),
            )
            conn.commit()

    # --- 行转模型 ---------------------------------------------------------

    def _row_to_account(self, row: sqlite3.Row) -> StoredAccount:
        return StoredAccount(
            uid=row["uid"],
            user_key=row["user_key"],
            unified_msg_origin=row["unified_msg_origin"],
            username=row["username"],
            cookie=self._decode_cookie(row["cookie"]),
            is_active=bool(row["is_active"]),
            last_status=row["last_status"],
            last_message=row["last_message"],
            last_run_at=row["last_run_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _decode_cookie(self, stored: str) -> str:
        if not stored:
            return ""
        try:
            return decrypt_secret(stored, self._cookie_key)
        except ValueError as exc:
            plugin_logger.error(f"Cookie 解密失败：{exc}")
            return ""


class CheckinStore:
    """``checkin_record`` 表的持久化层。

    与 ``AccountStore`` 解耦：签到记录按南+ UID 主键归档，与聊天用户绑定
    无关。``upsert_daily`` / ``upsert_weekly`` 单字段更新各自维度的状态。
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkin_record (
                    uid TEXT PRIMARY KEY,
                    last_daily_date TEXT NOT NULL DEFAULT '',
                    last_daily_status TEXT NOT NULL DEFAULT '',
                    last_daily_message TEXT NOT NULL DEFAULT '',
                    last_daily_error TEXT NOT NULL DEFAULT '',
                    last_weekly_date TEXT NOT NULL DEFAULT '',
                    last_weekly_status TEXT NOT NULL DEFAULT '',
                    last_weekly_message TEXT NOT NULL DEFAULT '',
                    last_weekly_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, uid: str) -> CheckinRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkin_record WHERE uid = ?", (uid,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def upsert_daily(
        self,
        uid: str,
        *,
        date: str,
        status: str,
        message: str,
        error: str = "",
    ) -> None:
        self._upsert_field(
            uid,
            updates={
                "last_daily_date": date,
                "last_daily_status": status,
                "last_daily_message": message,
                "last_daily_error": error,
            },
        )

    def upsert_weekly(
        self,
        uid: str,
        *,
        date: str,
        status: str,
        message: str,
        error: str = "",
    ) -> None:
        self._upsert_field(
            uid,
            updates={
                "last_weekly_date": date,
                "last_weekly_status": status,
                "last_weekly_message": message,
                "last_weekly_error": error,
            },
        )

    def _upsert_field(self, uid: str, *, updates: dict[str, str]) -> None:
        stamp = now_iso()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT uid FROM checkin_record WHERE uid = ?", (uid,)
            ).fetchone()
            if existing is None:
                full: dict[str, str] = {
                    "uid": uid,
                    "last_daily_date": "",
                    "last_daily_status": "",
                    "last_daily_message": "",
                    "last_daily_error": "",
                    "last_weekly_date": "",
                    "last_weekly_status": "",
                    "last_weekly_message": "",
                    "last_weekly_error": "",
                    "created_at": stamp,
                    "updated_at": stamp,
                }
                full.update(updates)
                conn.execute(
                    """
                    INSERT INTO checkin_record (
                        uid, last_daily_date, last_daily_status, last_daily_message,
                        last_daily_error, last_weekly_date, last_weekly_status,
                        last_weekly_message, last_weekly_error, created_at, updated_at
                    ) VALUES (
                        :uid, :last_daily_date, :last_daily_status, :last_daily_message,
                        :last_daily_error, :last_weekly_date, :last_weekly_status,
                        :last_weekly_message, :last_weekly_error, :created_at, :updated_at
                    )
                    """,
                    full,
                )
            else:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                params: dict[str, str] = {**updates, "uid": uid, "updated_at": stamp}
                conn.execute(
                    f"UPDATE checkin_record SET {set_clause}, updated_at = :updated_at WHERE uid = :uid",
                    params,
                )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CheckinRecord:
        return CheckinRecord(
            uid=row["uid"],
            last_daily_date=row["last_daily_date"],
            last_daily_status=row["last_daily_status"],
            last_daily_message=row["last_daily_message"],
            last_daily_error=row["last_daily_error"],
            last_weekly_date=row["last_weekly_date"],
            last_weekly_status=row["last_weekly_status"],
            last_weekly_message=row["last_weekly_message"],
            last_weekly_error=row["last_weekly_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
