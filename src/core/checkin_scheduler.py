"""自动签到调度器（schedule 表驱动）。

职责：
* 从 ``schedule`` 表恢复订阅，重启不丢失
* 按 ``(umo, task_key)`` 聚合调度：同一会话同一任务只创建一个 job
* 同一 job 触发时批量签到所有订阅者，推送一条汇总消息
* ``auto_checkin_cron`` 变更时批量更新 checkin 类订阅 cron
* ``asyncio.Semaphore`` 控制并发
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api.event import MessageChain

from ..shared.constants import (
    CHECKIN_TASK_KEY_ALL,
    CHECKIN_TASK_KEY_DAILY,
    CHECKIN_TASK_KEY_PREFIX,
    CHECKIN_TASK_KEY_SESSION,
    CHECKIN_TASK_KEY_WEEKLY,
)
from ..southplus.api import CheckinService
from ..southplus.models import CheckinStatus
from ..utils import current_iso_week, current_local_date
from ..utils.logger import plugin_logger
from .datamodels import UserRow
from .db.checkin_session_exclusion_store import CheckinSessionExclusionStore
from .db.checkin_store import CheckinStore
from .db.schedule_store import ScheduleStore
from .db.user_store import UserStore
from .tasks import TASK_REGISTRY, TaskContext, scan_task_modules
from .tasks.base import TaskResult

SendMessageFunc = Callable[[str, Any], Any]


@dataclass(slots=True)
class _PerUserResult:
    user: UserRow
    result: TaskResult
    skipped: bool
    daily_status: str = ""  # CheckinStatus value，"" 表示未执行
    weekly_status: str = ""  # CheckinStatus value，"" 表示未执行


class CheckinScheduler:
    def __init__(
        self,
        *,
        checkin_service: CheckinService,
        user_store: UserStore,
        checkin_store: CheckinStore,
        schedule_store: ScheduleStore,
        send_message: SendMessageFunc,
        exclusion_store: CheckinSessionExclusionStore | None = None,
    ) -> None:
        self._checkin_service = checkin_service
        self._user_store = user_store
        self._checkin_store = checkin_store
        self._schedule_store = schedule_store
        self._exclusion_store = exclusion_store
        self._send_message = send_message
        self._scheduler: AsyncIOScheduler | None = None
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, *, concurrency: int) -> None:
        if self._scheduler is not None:
            self.stop()

        scan_task_modules()
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        self._restore_on_boot()
        plugin_logger.info(f"自动签到调度已启动：concurrency={concurrency}")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            plugin_logger.info("自动签到调度已停止。")

    def reload_config(self, *, cron: str, concurrency: int) -> None:
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        affected_umos = self._schedule_store.batch_update_cron(
            task_key_prefix=CHECKIN_TASK_KEY_PREFIX,
            new_cron=cron,
        )
        # 按 (umo, task_key) 重建受影响的 job
        for umo in affected_umos:
            rows = self._schedule_store.list_by_umo(umo)
            task_keys = {r.task_key for r in rows if r.enabled}
            for tk in task_keys:
                self._ensure_job_for(umo, tk)
        plugin_logger.info(
            f"签到 cron 已批量更新为 {cron}，影响 {len(affected_umos)} 个会话。"
        )

    def refresh_job(self, umo: str, task_key: str) -> None:
        """公开刷新单个聚合 job，供 Dashboard 管理调度后重建运行态。"""
        self._ensure_job_for(umo, task_key)

    def refresh_checkin_jobs(self, umo: str) -> None:
        """刷新当前会话下两个签到聚合 job，供会话级排除变更后调用。"""
        for task_key in (CHECKIN_TASK_KEY_ALL, CHECKIN_TASK_KEY_SESSION):
            self._ensure_job_for(umo, task_key)

    # ------------------------------------------------------------------
    # 订阅管理（持久化到 schedule 表）
    # ------------------------------------------------------------------

    def subscribe(
        self,
        umo: str,
        task_key: str,
        cron: str,
        params: dict[str, Any],
    ) -> None:
        params_json = json.dumps(params, ensure_ascii=False)
        self._schedule_store.subscribe(
            umo=umo,
            task_key=task_key,
            cron=cron,
            params_json=params_json,
        )
        self._ensure_job_for(umo, task_key)
        plugin_logger.debug(f"订阅已持久化：umo={umo}, task_key={task_key}")

    def unsubscribe(self, umo: str, task_key: str, params: dict[str, Any]) -> None:
        params_json = json.dumps(params, ensure_ascii=False)
        self._schedule_store.unsubscribe(
            umo=umo,
            task_key=task_key,
            params_json=params_json,
        )
        # 重建（如果没有剩余订阅，job 会被移除）
        self._ensure_job_for(umo, task_key)
        plugin_logger.debug(f"订阅已移除：umo={umo}, task_key={task_key}")

    def is_subscribed(self, umo: str, task_key: str, params: dict[str, Any]) -> bool:
        params_json = json.dumps(params, ensure_ascii=False)
        return self._schedule_store.is_subscribed(
            umo=umo,
            task_key=task_key,
            params_json=params_json,
        )

    # ------------------------------------------------------------------
    # 手动全量执行（/spallcheckin）
    # ------------------------------------------------------------------

    async def run_all_checkins(self) -> str:
        """立即执行全部活跃账号签到，返回全局统计文本。"""
        users = self._user_store.list_all()
        if not users:
            return "South Plus 主动签到（全体账号）：无绑定账号。"

        semaphore = self._semaphore or asyncio.Semaphore(3)
        task_futures = [self._checkin_user(user, semaphore) for user in users]
        raw = await asyncio.gather(*task_futures)
        results: list[_PerUserResult] = [r for r in raw if r is not None]

        return _format_global_report(results)

    # ------------------------------------------------------------------
    # 内部：job 调度（按 umo + task_key 聚合）
    # ------------------------------------------------------------------

    def _restore_on_boot(self) -> None:
        rows = self._schedule_store.list_all_enabled()
        # 按 (umo, task_key) 去重，每个组合只创建一个 job
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.umo, row.task_key)
            if key in seen:
                continue
            seen.add(key)
            self._ensure_job_for(row.umo, row.task_key)
        plugin_logger.info(
            f"从 schedule 表恢复了 {len(rows)} 行订阅，创建了 {len(seen)} 个聚合 job。"
        )

    def _ensure_job_for(self, umo: str, task_key: str) -> None:
        """确保 (umo, task_key) 有正确的 APScheduler job。

        如果该组合下还有 enabled 行 → 创建/更新 job；
        如果没有 → 移除 job。
        """
        if self._scheduler is None:
            return
        # 签到类任务有专用执行路径，不经过 TASK_REGISTRY。
        if (
            not task_key.startswith(CHECKIN_TASK_KEY_PREFIX)
            and task_key not in TASK_REGISTRY
        ):
            return

        job_id = _job_id_for_key(umo, task_key)

        # 查询该 (umo, task_key) 下是否还有 enabled 订阅
        rows = self._schedule_store.list_by_umo(umo)
        matching = [r for r in rows if r.task_key == task_key and r.enabled]

        if not matching:
            # 没有订阅者 → 移除 job
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            return

        # 取 cron（同一 umo + task_key 下的 cron 应相同）
        cron = matching[0].cron
        try:
            trigger = CronTrigger.from_crontab(cron)
        except Exception:
            plugin_logger.warning(f"无效 cron，跳过：umo={umo} cron={cron}")
            return

        self._scheduler.add_job(
            self._tick_for_key,
            trigger=trigger,
            id=job_id,
            args=[umo, task_key],
            replace_existing=True,
        )

    # ------------------------------------------------------------------
    # 聚合 tick：一个 (umo, task_key) 触发一次
    # ------------------------------------------------------------------

    async def _tick_for_key(self, umo: str, task_key: str) -> None:
        """单个 (umo, task_key) 聚合触发。"""
        # 签到类任务有专用执行路径，不查 TASK_REGISTRY。
        is_checkin = task_key.startswith(CHECKIN_TASK_KEY_PREFIX)
        task_cls = None
        if not is_checkin:
            task_cls = TASK_REGISTRY.get(task_key)
            if task_cls is None:
                plugin_logger.warning(f"未知 task_key，跳过：{task_key}")
                return

        # 收集所有 enabled 订阅
        rows = self._schedule_store.list_by_umo(umo)
        matching = [r for r in rows if r.task_key == task_key and r.enabled]
        if not matching:
            return

        # 从订阅中收集去重的用户列表
        seen_uids: set[str] = set()
        users: list[UserRow] = []
        has_all_mode = False
        excluded_uids = (
            self._exclusion_store.list_uids(umo)
            if is_checkin and self._exclusion_store
            else set()
        )

        for row in matching:
            params = json.loads(row.params_json) if row.params_json else {}
            mode = params.get("mode", "session")
            if mode == "all":
                has_all_mode = True
            else:
                account = params.get("account", "")
                if account:
                    active = self._get_active_for_account(account)
                    if (
                        active
                        and active.auto_checkin
                        and active.sp_uid not in excluded_uids
                        and active.sp_uid not in seen_uids
                    ):
                        seen_uids.add(active.sp_uid)
                        users.append(active)

        if has_all_mode:
            for u in self._user_store.list_all():
                if (
                    u.sp_uid not in seen_uids
                    and u.sp_uid not in excluded_uids
                    and u.auto_checkin
                ):
                    seen_uids.add(u.sp_uid)
                    users.append(u)

        if not users:
            plugin_logger.debug(f"聚合 tick：无用户，跳过 umo={umo}")
            return

        # 批量签到（Semaphore 并发控制）
        # 签到类任务同时跑日签+周签，其余走单任务
        semaphore = self._semaphore or asyncio.Semaphore(3)
        if is_checkin:
            per_user_tasks = [self._checkin_user(user, semaphore) for user in users]
        else:
            assert task_cls is not None
            per_user_tasks = [
                self._run_task_for_user(user, task_cls, {}, semaphore) for user in users
            ]
        raw: list[_PerUserResult | None] = await asyncio.gather(*per_user_tasks)
        results = [r for r in raw if r is not None]

        if results:
            await self._push_report(umo, task_key, results)

    # ------------------------------------------------------------------
    # 单用户任务执行
    # ------------------------------------------------------------------

    async def _run_task_for_user(
        self,
        user: UserRow,
        task_cls: type,  # type: ignore[type-arg]
        params: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> _PerUserResult | None:
        async with semaphore:
            return await self._do_run_task(user, task_cls, params)

    async def _do_run_task(
        self,
        user: UserRow,
        task_cls: type,  # type: ignore[type-arg]
        params: dict[str, Any],
    ) -> _PerUserResult | None:
        today = current_local_date()
        this_week = current_iso_week()
        task_key = task_cls.TASK_KEY
        period_key = today if "daily" in task_key else this_week

        # 跳过已签
        cached_status = _normalise_cached_status(
            self._checkin_store.get_genuine_status(
                sp_uid=user.sp_uid,
                task_key=task_key,
                period_key=period_key,
            )
        )
        if cached_status:
            return _PerUserResult(
                user=user,
                result=TaskResult(
                    status=cached_status,
                    message="（跳过，已签到）"
                    if cached_status == CheckinStatus.ALREADY_DONE.value
                    else "（缓存，本期已成功）",
                ),
                skipped=cached_status == CheckinStatus.ALREADY_DONE.value,
            )

        try:
            task = task_cls(checkin_service=self._checkin_service)
            ctx = TaskContext(sp_uid=user.sp_uid, cookie=user.cookie, params=params)
            result = await task.run(ctx)
        except Exception as exc:
            plugin_logger.exception(f"任务异常 uid={user.sp_uid} task_key={task_key}")
            result = TaskResult(
                status=CheckinStatus.FAILED.value,
                message=f"签到异常：{exc}",
                error=repr(exc),
            )

        # 写入 checkin_record
        self._checkin_store.record(
            sp_uid=user.sp_uid,
            task_key=task_key,
            period_key=period_key,
            status=result.status,
            message=result.message,
            error=result.error,
        )

        return _PerUserResult(user=user, result=result, skipped=False)

    async def _checkin_user(
        self,
        user: UserRow,
        semaphore: asyncio.Semaphore,
    ) -> _PerUserResult | None:
        """全量签到入口（/spallcheckin）：同时跑日签+周签。"""
        async with semaphore:
            return await self._do_checkin_both(user)

    async def _do_checkin_both(self, user: UserRow) -> _PerUserResult | None:
        today = current_local_date()
        this_week = current_iso_week()

        daily_cached_status = _normalise_cached_status(
            self._checkin_store.get_genuine_status(
                sp_uid=user.sp_uid,
                task_key=CHECKIN_TASK_KEY_DAILY,
                period_key=today,
            )
        )
        weekly_cached_status = _normalise_cached_status(
            self._checkin_store.get_genuine_status(
                sp_uid=user.sp_uid,
                task_key=CHECKIN_TASK_KEY_WEEKLY,
                period_key=this_week,
            )
        )
        daily_skip = bool(daily_cached_status)
        weekly_skip = bool(weekly_cached_status)

        try:
            if not daily_skip and not weekly_skip:
                report = await asyncio.to_thread(
                    self._checkin_service.checkin,
                    user.cookie,
                )
                daily_result = report.daily
                weekly_result = report.weekly
            elif daily_skip and weekly_skip:
                return _PerUserResult(
                    user=user,
                    result=TaskResult(
                        status=CheckinStatus.SUCCESS.value, message="（跳过，已签到）"
                    ),
                    skipped=(
                        daily_cached_status == CheckinStatus.ALREADY_DONE.value
                        and weekly_cached_status == CheckinStatus.ALREADY_DONE.value
                    ),
                    daily_status=daily_cached_status,
                    weekly_status=weekly_cached_status,
                )
            elif not daily_skip:
                daily_result = await asyncio.to_thread(
                    self._checkin_service.checkin_daily,
                    user.cookie,
                )
                weekly_result = None
            else:
                daily_result = None
                weekly_result = await asyncio.to_thread(
                    self._checkin_service.checkin_weekly,
                    user.cookie,
                )
        except Exception as exc:
            plugin_logger.exception(f"全量签到异常 uid={user.sp_uid}")
            return _PerUserResult(
                user=user,
                result=TaskResult(
                    status=CheckinStatus.FAILED.value, message=str(exc), error=repr(exc)
                ),
                skipped=False,
                daily_status=CheckinStatus.FAILED.value
                if not daily_skip
                else daily_cached_status,
                weekly_status=CheckinStatus.FAILED.value
                if not weekly_skip
                else weekly_cached_status,
            )

        # 维度状态
        ds = (
            (
                daily_result.status.value
                if daily_result
                else daily_cached_status or CheckinStatus.ALREADY_DONE.value
            )
            if not daily_skip
            else daily_cached_status
        )
        ws = (
            (
                weekly_result.status.value
                if weekly_result
                else weekly_cached_status or CheckinStatus.ALREADY_DONE.value
            )
            if not weekly_skip
            else weekly_cached_status
        )

        if not daily_skip and daily_result:
            self._checkin_store.record(
                sp_uid=user.sp_uid,
                task_key=CHECKIN_TASK_KEY_DAILY,
                period_key=today,
                status=daily_result.status.value,
                message=daily_result.message,
                error=daily_result.error,
            )
        if not weekly_skip and weekly_result:
            self._checkin_store.record(
                sp_uid=user.sp_uid,
                task_key=CHECKIN_TASK_KEY_WEEKLY,
                period_key=this_week,
                status=weekly_result.status.value,
                message=weekly_result.message,
                error=weekly_result.error,
            )

        return _PerUserResult(
            user=user,
            result=TaskResult(
                status=CheckinStatus.SUCCESS.value
                if ds != CheckinStatus.FAILED.value and ws != CheckinStatus.FAILED.value
                else CheckinStatus.FAILED.value,
                message="",
            ),
            skipped=False,
            daily_status=ds,
            weekly_status=ws,
        )

    # ------------------------------------------------------------------
    # 推送回执（聚合版）
    # ------------------------------------------------------------------

    async def _push_report(
        self,
        umo: str,
        task_key: str,
        results: list[_PerUserResult],
    ) -> None:
        """推送一条聚合签到回执到会话，失败用户用 @ 提醒。"""
        if not results:
            return
        try:
            text, failed = _format_aggregated_report(results, task_key=task_key)
            chain = MessageChain().message(text)
            for r in failed:
                # name 留空（跨平台不一定有昵称），qq 用平台 account
                chain.at(name="", qq=r.user.account)
            await self._send_message(umo, chain)
        except Exception as exc:
            plugin_logger.exception(f"推送签到回执失败 umo={umo}: {exc}")

    def _get_active_for_account(self, account: str) -> UserRow | None:
        """按 account 查找活跃用户（session 模式）。"""
        if not account:
            return None
        users = self._user_store.list_all()
        for u in users:
            if u.account == account and u.is_active:
                return u
        return None


# ------------------------------------------------------------------
# helper
# ------------------------------------------------------------------


def _job_id_for_key(umo: str, task_key: str) -> str:
    """按 (umo, task_key) 生成稳定的 job ID。"""
    raw = f"{umo}::{task_key}"
    digest = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"sp_agg_{digest}"


def _is_failed(result: _PerUserResult) -> bool:
    return result.result.status == CheckinStatus.FAILED.value


def _normalise_cached_status(status: object) -> str:
    if status == CheckinStatus.SUCCESS.value:
        return CheckinStatus.SUCCESS.value
    if status == CheckinStatus.ALREADY_DONE.value:
        return CheckinStatus.ALREADY_DONE.value
    return ""


@dataclass(slots=True)
class _ReportStats:
    total: int
    completed: int
    daily_ok: int
    daily_skip: int
    daily_fail: int
    weekly_ok: int
    weekly_skip: int
    weekly_fail: int
    failed: list[_PerUserResult]


def _build_report_stats(results: list[_PerUserResult]) -> _ReportStats:
    daily_ok = daily_skip = daily_fail = 0
    weekly_ok = weekly_skip = weekly_fail = 0
    completed = 0
    failed: list[_PerUserResult] = []

    for r in results:
        ds, ws = r.daily_status, r.weekly_status
        if ds == CheckinStatus.FAILED.value:
            daily_fail += 1
        elif ds == CheckinStatus.ALREADY_DONE.value:
            daily_skip += 1
        elif ds:
            daily_ok += 1

        if ws == CheckinStatus.FAILED.value:
            weekly_fail += 1
        elif ws == CheckinStatus.ALREADY_DONE.value:
            weekly_skip += 1
        elif ws:
            weekly_ok += 1

        if ds == CheckinStatus.FAILED.value or ws == CheckinStatus.FAILED.value:
            failed.append(r)
        else:
            completed += 1

    return _ReportStats(
        total=len(results),
        completed=completed,
        daily_ok=daily_ok,
        daily_skip=daily_skip,
        daily_fail=daily_fail,
        weekly_ok=weekly_ok,
        weekly_skip=weekly_skip,
        weekly_fail=weekly_fail,
        failed=failed,
    )


def _format_task_line(label: str, ok: int, skip: int, fail: int) -> str:
    return f"{label}：✅ {ok}  ⏭️ {skip}  ❌ {fail}"


TaskLineFormatter = Callable[[str, int, int, int], str]


def _format_checkin_summary(
    title: str,
    stats: _ReportStats,
    *,
    line_formatter: TaskLineFormatter = _format_task_line,
) -> str:
    lines = [
        title,
        f"南+账号：{stats.total} 个",
        f"完成 {stats.completed}：✅ 成功 {stats.completed}",
        line_formatter("社区·日签", stats.daily_ok, stats.daily_skip, stats.daily_fail),
        line_formatter(
            "社区·周签", stats.weekly_ok, stats.weekly_skip, stats.weekly_fail
        ),
    ]
    return "\n".join(lines)


def _format_active_task_line(label: str, ok: int, skip: int, fail: int) -> str:
    return f"{label}：✅ {ok}  ⏭️ 请勿重复签到 {skip}  ❌ {fail}"


def _format_aggregated_report(
    results: list[_PerUserResult],
    *,
    task_key: str = "",
) -> tuple[str, list[_PerUserResult]]:
    """格式化订阅推送：账号范围 + 日签/周签三态统计 + 返回失败列表供调用方 @。

    Returns:
        (text, failed) — text 是统计摘要，failed 是失败用户列表。
    """
    stats = _build_report_stats(results)
    text = _format_checkin_summary(_subscription_report_title(task_key), stats)
    return text, stats.failed


def _subscription_report_title(task_key: str) -> str:
    if task_key == CHECKIN_TASK_KEY_ALL:
        return "South Plus 自动签到（全局订阅）"
    if task_key == CHECKIN_TASK_KEY_SESSION:
        return "South Plus 自动签到（会话订阅）"
    return "South Plus 自动签到"


def _format_global_report(results: list[_PerUserResult]) -> str:
    return _format_checkin_summary(
        "South Plus 主动签到（全体账号）",
        _build_report_stats(results),
        line_formatter=_format_active_task_line,
    )
