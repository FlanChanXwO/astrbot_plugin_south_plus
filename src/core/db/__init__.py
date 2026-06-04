"""针对 5 张新表的 Store 集合。

每个 Store 负责自己的 DDL + 增删改查；共享 ``_connect`` 工厂。
"""

from __future__ import annotations

from ._connection import connect as _db_connect
from .checkin_store import CheckinStore
from .group_store import GroupStore
from .schedule_store import ScheduleStore
from .user_group_store import UserGroupStore
from .user_store import UserStore

__all__ = [
    "CheckinStore",
    "GroupStore",
    "ScheduleStore",
    "UserGroupStore",
    "UserStore",
    "_db_connect",
]
