"""任务抽象基类。

``ScheduledTask`` 定义了调度器可执行的签约：TASK_KEY、DEFAULT_CRON、
以及 ``run(ctx) -> TaskResult``。新任务类型通过 ``@register_task``
注册到模块级 ``TASK_REGISTRY``，调度器按 task_key 查类实例化。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(slots=True)
class TaskContext:
    """单次任务执行的上下文，由调度器在 tick 时填充。"""

    sp_uid: str
    cookie: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskResult:
    """单次任务执行的返回。status 兼容 ``CheckinStatus`` 枚举值。"""

    status: str  # SUCCESS | ALREADY_DONE | FAILED
    message: str
    error: str = ""


class ScheduledTask(ABC):
    """调度器可执行的任务单元。

    子类必须声明：

    * ``TASK_KEY`` — 唯一任务标识，如 ``"sp.checkin.daily"``。
    * ``DEFAULT_CRON`` — 本任务默认 cron，优先级低于 schedule 表 cron。
    * ``run(ctx)`` — 任务执行逻辑。
    """

    TASK_KEY: ClassVar[str]
    DEFAULT_CRON: ClassVar[str]

    @abstractmethod
    async def run(self, ctx: TaskContext) -> TaskResult:
        """执行本任务，返回结构化结果。"""
