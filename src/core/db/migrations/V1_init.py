"""V1 初始化迁移。

创建插件全部 SQLite 表：user, checkin_record, group, schedule, user_group,
以及迁移记录表 sp_migration_record。
"""

from __future__ import annotations

import sqlite3

from ....utils.logger import plugin_logger as _log


def upgrade(conn: sqlite3.Connection) -> None:
    def _table_exists(table: str) -> bool:
        return (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is not None
        )

    def _index_exists(index: str) -> bool:
        return (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index,)
            ).fetchone()
            is not None
        )

    if not _table_exists("user"):
        conn.execute(
            """
            CREATE TABLE "user" (
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
        _log.info("迁移 V1: 创建 user 表")

    if not _index_exists("idx_user_account_platform"):
        conn.execute(
            'CREATE INDEX idx_user_account_platform ON "user"(account, platform)'
        )
        _log.info("迁移 V1: 创建 idx_user_account_platform 索引")

    if not _table_exists("checkin_record"):
        conn.execute(
            """
            CREATE TABLE checkin_record (
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
        _log.info("迁移 V1: 创建 checkin_record 表")

    if not _index_exists("idx_checkin_lookup"):
        conn.execute(
            "CREATE INDEX idx_checkin_lookup ON checkin_record(sp_uid, task_key, period_key)"
        )
        _log.info("迁移 V1: 创建 idx_checkin_lookup 索引")

    if not _table_exists("group"):
        conn.execute(
            """
            CREATE TABLE "group" (
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
        _log.info("迁移 V1: 创建 group 表")

    if not _table_exists("schedule"):
        conn.execute(
            """
            CREATE TABLE schedule (
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
        _log.info("迁移 V1: 创建 schedule 表")

    if not _table_exists("user_group"):
        conn.execute(
            """
            CREATE TABLE user_group (
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
        _log.info("迁移 V1: 创建 user_group 表")

    if not _table_exists("sp_migration_record"):
        conn.execute(
            """
            CREATE TABLE sp_migration_record (
                version     VARCHAR(32) PRIMARY KEY,
                applied_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                description VARCHAR(256)
            )
            """
        )
        _log.info("迁移 V1: 创建 sp_migration_record 表")

    _log.info("迁移 V1 完成")
