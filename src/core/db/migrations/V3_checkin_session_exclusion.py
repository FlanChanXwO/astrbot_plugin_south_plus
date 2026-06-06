"""V3 会话级自动签到排除表。

该表只表达 Dashboard 对某个会话 ``umo`` 的排除关系，不改变用户自己的
``user.auto_checkin`` 全局开关，也不修改 ``schedule.params_json``。
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

    if not _table_exists("checkin_session_exclusion"):
        conn.execute(
            """
            CREATE TABLE checkin_session_exclusion (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                umo          TEXT NOT NULL,
                sp_uid       TEXT NOT NULL REFERENCES "user"(sp_uid),
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                UNIQUE(umo, sp_uid)
            )
            """
        )
        _log.info("迁移 V3: 创建 checkin_session_exclusion 表")

    if not _index_exists("idx_checkin_session_exclusion_umo"):
        conn.execute(
            "CREATE INDEX idx_checkin_session_exclusion_umo "
            "ON checkin_session_exclusion(umo)"
        )
        _log.info("迁移 V3: 创建 idx_checkin_session_exclusion_umo 索引")

    _log.info("迁移 V3 完成")
