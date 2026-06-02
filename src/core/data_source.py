from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..utils import decrypt_secret, encrypt_secret, now_iso
from .datamodels import StoredCredential
from .logger import plugin_logger


class CredentialStore:
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
                CREATE TABLE IF NOT EXISTS credentials (
                    user_key TEXT PRIMARY KEY,
                    unified_msg_origin TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    cookie TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    schedule_time TEXT NOT NULL DEFAULT '',
                    last_status TEXT NOT NULL DEFAULT '',
                    last_message TEXT NOT NULL DEFAULT '',
                    last_run_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def upsert_credential(
        self,
        *,
        user_key: str,
        unified_msg_origin: str,
        username: str,
        cookie: str,
        enabled: bool = True,
        schedule_time: str = "",
    ) -> None:
        stamp = now_iso()
        encrypted_cookie = encrypt_secret(cookie, self._cookie_key) if cookie else ""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO credentials (
                    user_key, unified_msg_origin, username, cookie, enabled,
                    schedule_time, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_key) DO UPDATE SET
                    unified_msg_origin = excluded.unified_msg_origin,
                    username = excluded.username,
                    cookie = excluded.cookie,
                    enabled = excluded.enabled,
                    schedule_time = excluded.schedule_time,
                    updated_at = excluded.updated_at
                """,
                (
                    user_key,
                    unified_msg_origin,
                    username,
                    encrypted_cookie,
                    1 if enabled else 0,
                    schedule_time,
                    stamp,
                    stamp,
                ),
            )
            conn.commit()

    def update_run_result(
        self,
        user_key: str,
        *,
        status: str,
        message: str,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE credentials
                SET last_status = ?, last_message = ?, last_run_at = ?, updated_at = ?
                WHERE user_key = ?
                """,
                (status, message, now_iso(), now_iso(), user_key),
            )
            conn.commit()

    def set_enabled(self, user_key: str, enabled: bool) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE credentials SET enabled = ?, updated_at = ? WHERE user_key = ?",
                (1 if enabled else 0, now_iso(), user_key),
            )
            conn.commit()

    def set_schedule(self, user_key: str, schedule_time: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE credentials SET schedule_time = ?, updated_at = ? WHERE user_key = ?",
                (schedule_time, now_iso(), user_key),
            )
            conn.commit()

    def delete(self, user_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM credentials WHERE user_key = ?", (user_key,))
            conn.commit()

    def get(self, user_key: str) -> StoredCredential | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM credentials WHERE user_key = ?",
                (user_key,),
            ).fetchone()
        return self._row_to_credential(row) if row else None

    def list_all(self) -> list[StoredCredential]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM credentials ORDER BY updated_at DESC",
            ).fetchall()
        return [self._row_to_credential(row) for row in rows]

    def _row_to_credential(self, row: sqlite3.Row) -> StoredCredential:
        return StoredCredential(
            user_key=row["user_key"],
            unified_msg_origin=row["unified_msg_origin"],
            username=row["username"],
            cookie=self._decode_cookie(row["cookie"]),
            enabled=bool(row["enabled"]),
            schedule_time=row["schedule_time"],
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
