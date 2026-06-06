"""针对 5 张新表的 Store 集合。

每个 Store 负责自己的 DDL + 增删改查；共享 ``_connect`` 工厂。
``setup_db`` 在 Store 实例化前运行版本化迁移。
"""

from __future__ import annotations

from pathlib import Path

from ._connection import connect as _db_connect
from .checkin_session_exclusion_store import CheckinSessionExclusionStore
from .checkin_store import CheckinStore
from .group_store import GroupStore
from .schedule_store import ScheduleStore
from .user_group_store import UserGroupStore
from .user_store import UserStore

__all__ = [
    "CheckinSessionExclusionStore",
    "CheckinStore",
    "GroupStore",
    "ScheduleStore",
    "UserGroupStore",
    "UserStore",
    "_db_connect",
    "setup_db",
]


def setup_db(db_path: Path) -> None:
    """在所有 Store 实例化前运行版本化迁移。幂等，可安全重复调用。"""
    from .migrations.migration_runner import run_migrations

    with _db_connect(db_path) as conn:
        run_migrations(conn)
        conn.commit()
