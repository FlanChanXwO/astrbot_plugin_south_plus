"""签到任务实现：日签 cid=15 + 周签 cid=14。

这两个任务共享同一个 cron，由 ``auto_checkin_cron`` 配置统一控制。
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from ...shared.constants import CHECKIN_TASK_KEY_DAILY, CHECKIN_TASK_KEY_WEEKLY
from ...southplus.api import CheckinService
from . import register_task
from .base import ScheduledTask, TaskContext, TaskResult


@register_task
class DailyCheckinTask(ScheduledTask):
    TASK_KEY: ClassVar[str] = CHECKIN_TASK_KEY_DAILY
    DEFAULT_CRON: ClassVar[str] = "0 8 * * *"

    def __init__(self, checkin_service: CheckinService) -> None:
        self._service = checkin_service

    async def run(self, ctx: TaskContext) -> TaskResult:
        result = await asyncio.to_thread(
            self._service.checkin_daily,
            ctx.cookie,
        )
        return TaskResult(
            status=result.status.value,
            message=result.message,
            error=result.error,
        )


@register_task
class WeeklyCheckinTask(ScheduledTask):
    TASK_KEY: ClassVar[str] = CHECKIN_TASK_KEY_WEEKLY
    DEFAULT_CRON: ClassVar[str] = "0 8 * * *"

    def __init__(self, checkin_service: CheckinService) -> None:
        self._service = checkin_service

    async def run(self, ctx: TaskContext) -> TaskResult:
        result = await asyncio.to_thread(
            self._service.checkin_weekly,
            ctx.cookie,
        )
        return TaskResult(
            status=result.status.value,
            message=result.message,
            error=result.error,
        )
