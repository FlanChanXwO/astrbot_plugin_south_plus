"""V2 迁移：为 user 表添加 auto_checkin 字段。"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute('PRAGMA table_info("user")').fetchall()}
    if "auto_checkin" not in cols:
        conn.execute(
            'ALTER TABLE "user" ADD COLUMN auto_checkin INTEGER NOT NULL DEFAULT 1'
        )
