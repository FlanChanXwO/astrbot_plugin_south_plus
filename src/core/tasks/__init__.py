"""任务注册中心。

``@register_task`` 装饰器把 ``ScheduledTask`` 子类登记进 ``TASK_REGISTRY``；
``scan_task_modules()`` 在插件启动时扫描本包模块以触发装饰器。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from .base import ScheduledTask, TaskContext, TaskResult

TASK_REGISTRY: dict[str, type[ScheduledTask]] = {}


def register_task(cls: type[ScheduledTask]) -> type[ScheduledTask]:
    if not cls.TASK_KEY:
        raise ValueError(f"{cls.__name__} 必须声明 TASK_KEY")
    if cls.TASK_KEY in TASK_REGISTRY:
        raise KeyError(
            f"TASK_KEY 冲突：{cls.TASK_KEY}（{TASK_REGISTRY[cls.TASK_KEY].__name__} 已注册）"
        )
    TASK_REGISTRY[cls.TASK_KEY] = cls
    return cls


def scan_task_modules() -> None:
    """导入本包下除 __init__ / base 外的所有模块，触发 @register_task 装饰器。"""
    _pkg = Path(__file__).parent
    for f in _pkg.glob("*.py"):
        mod_name = f.stem
        if mod_name.startswith("_") or mod_name in ("__init__", "base"):
            continue
        import_module(f".{mod_name}", __package__)


__all__ = [
    "ScheduledTask",
    "TaskContext",
    "TaskResult",
    "TASK_REGISTRY",
    "register_task",
    "scan_task_modules",
]
