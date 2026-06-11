from __future__ import annotations

import asyncio
import io
import tempfile
import time
from pathlib import Path

import qrcode

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import PermissionType
from astrbot.api.message_components import Image as CompImage
from astrbot.api.message_components import Node, Plain
from astrbot.api.star import Context, Star

from .src.web.auth_server import CredentialFormServer
from .src.core.checkin_scheduler import CheckinScheduler
from .src.core.config_manager import PluginConfigManager
from .src.core.db import (
    CheckinSessionExclusionStore,
    CheckinStore,
    GroupStore,
    ScheduleStore,
    UserGroupStore,
    UserStore,
    setup_db,
)
from .src.core.datamodels import CredentialSession
from .src.pages import register_page_apis
from .src.utils.logger import plugin_logger
from .src.render.card_render import render_user_card
from .src.shared.constants import (
    CHECKIN_TASK_KEY_ALL,
    CHECKIN_TASK_KEY_DAILY,
    CHECKIN_TASK_KEY_SESSION,
    CHECKIN_TASK_KEY_WEEKLY,
    PLUGIN_NAME,
)
from .src.southplus.api import (
    CheckinReport,
    CheckinService,
    CheckinTaskResult,
    LoginRequest,
    LoginResult,
    SouthPlusLoginApi,
    SouthPlusLoginError,
    SouthPlusProfileApi,
    SouthPlusProfileError,
    SouthPlusSession,
)
from .src.utils import (
    current_iso_week,
    current_iso_week_label,
    current_local_date,
    format_add_account_result,
    format_checkin_response,
    get_event_platform,
    is_aiocqhttp_event,
    season_name,
    wrap_docs_link,
)


_CHECKIN_REPORT_SCOPE_CURRENT = "当前账号"
_CHECKIN_REPORT_SCOPE_ALL = "全部账号"
_CHECKIN_REPORT_SUBSCRIBE_HINT = (
    "本命令不会立即执行签到，后续将按自动签到时间推送结果。"
)


def _checkin_report_subscribed_message(scope: str) -> str:
    return f"已订阅本会话的签到汇报（{scope}）。{_CHECKIN_REPORT_SUBSCRIBE_HINT}"


def _checkin_report_unsubscribed_message(scope: str) -> str:
    return f"已取消本会话的签到汇报订阅（{scope}）。"


def _checkin_report_not_subscribed_message(scope: str) -> str:
    return f"当前会话未订阅签到汇报（{scope}）。"


class SouthPlusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self._loop = asyncio.get_event_loop()
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self.config_manager = PluginConfigManager(self.config)
        self.config_snapshot = self.config_manager.snapshot()
        db_path = self.config_snapshot.database_path
        setup_db(db_path)
        self.store = UserStore(db_path)
        self.checkin_store = CheckinStore(db_path)
        self.checkin_exclusion_store = CheckinSessionExclusionStore(db_path)
        self.group_store = GroupStore(db_path)
        self.user_group_store = UserGroupStore(db_path)
        self.schedule_store = ScheduleStore(db_path)
        self.session = SouthPlusSession(
            self.config_snapshot.endpoints,
            http_proxy=self.config_snapshot.http_proxy,
        )
        self.client = SouthPlusLoginApi(self.session)
        self.profile_client = SouthPlusProfileApi(self.session)
        self.checkin_client = CheckinService(self.session)
        self.scheduler = CheckinScheduler(
            checkin_service=self.checkin_client,
            user_store=self.store,
            checkin_store=self.checkin_store,
            schedule_store=self.schedule_store,
            exclusion_store=self.checkin_exclusion_store,
            send_message=self.context.send_message,  # type: ignore[union-attr]
        )
        self.form_server = CredentialFormServer(
            config=self.config_snapshot.auth_server,
            client=self.client,
            on_login_success=self._handle_login_success,
        )
        register_page_apis(
            context,
            user_store=self.store,
            group_store=self.group_store,
            user_group_store=self.user_group_store,
            schedule_store=self.schedule_store,
            checkin_store=self.checkin_store,
            exclusion_store=self.checkin_exclusion_store,
            scheduler=self.scheduler,
        )
        self._reload_runtime_config()
        if self.config_snapshot.auto_checkin_enabled:
            self.scheduler.start(
                concurrency=self.config_snapshot.auto_checkin_concurrency,
            )
        plugin_logger.info("South Plus plugin initialized.")

    # ------------------------------------------------------------------
    # 登录链接
    # ------------------------------------------------------------------

    @filter.command("splogin", alias={"sp登陆"})
    async def sp_login(self, event: AstrMessageEvent):
        """生成一次性网页登录链接。每次登录成功会自动新增/刷新一条 UID 绑定。"""
        session = self.form_server.create_session(
            user_key=event.get_sender_id(),
            unified_msg_origin=event.unified_msg_origin,
            platform=get_event_platform(event),
        )
        self._expiry_tasks[session.token] = asyncio.create_task(
            self._expire_login_later(session)
        )
        url = self.form_server.build_url(session.token)
        ttl = self.config_snapshot.auth_server.token_ttl_seconds
        minutes = max(1, ttl // 60)

        strategy = self.config_snapshot.login_link_strategy
        use_docs = self.config_snapshot.use_docs_link_wrapper
        use_forward = self.config_snapshot.use_forward_node and is_aiocqhttp_event(
            event
        )

        # --- 构建消息组件 ---
        components: list = []

        if strategy in ("qrcode", "both"):
            # 生成 QR 码图片
            qr_img = qrcode.make(url)
            buf = io.BytesIO()
            qr_img.save(buf, format="PNG")
            qr_bytes = buf.getvalue()

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            try:
                tmp.write(qr_bytes)
                tmp.flush()
            finally:
                tmp.close()

            components.append(CompImage.fromFileSystem(str(Path(tmp.name))))

        if strategy in ("text", "both"):
            display_url = wrap_docs_link(url) if use_docs else url
            if use_docs:
                text = (
                    f"请复制地址到浏览器打开\n"
                    f"{display_url}\n"
                    f"登录地址{minutes}分钟内有效"
                )
            else:
                text = (
                    f"请在 {minutes} 分钟内打开并提交登录表单：\n"
                    f"{url}\n"
                    "页面会代理拉取站点验证码，请手动填写。"
                )
            components.append(Plain(text))

        if not components:
            # 兜底：strategy 值异常时走纯文字
            components.append(Plain(f"登录链接：{url}（{minutes} 分钟内有效）"))

        # --- 决定发送方式 ---
        if use_forward:
            node = Node(
                uin=event.get_self_id(),
                name=PLUGIN_NAME,
                content=components,
            )
            yield event.chain_result([node])
        elif len(components) == 1 and isinstance(components[0], Plain):
            yield event.plain_result(components[0].text)
        else:
            yield event.chain_result(components)

    # ------------------------------------------------------------------
    # 账号管理命令
    # ------------------------------------------------------------------

    @filter.command("spstatus", alias={"sp状态"})
    async def sp_status(self, event: AstrMessageEvent):
        """查看当前激活账号。"""
        account = event.get_sender_id()
        platform = get_event_platform(event)
        active = self.store.get_active(account, platform)
        accounts = self.store.list_for_account(account, platform)
        if not active and not accounts:
            yield event.plain_result(
                "当前账号尚未绑定 South Plus 凭证。\n请用 /splogin 登录。"
            )
            return
        if not active:
            yield event.plain_result(
                f"绑定了 {len(accounts)} 个 UID，但当前没有激活账号。\n"
                "用 /spswitch <uid> 切换。"
            )
            return
        yield event.plain_result(
            f"当前激活账号：\nUID：{active.sp_uid}\n绑定总数：{len(accounts)}\n"
        )

    @filter.command("spuidlist", alias={"spuid列表"})
    async def sp_uid_list(self, event: AstrMessageEvent):
        """列出当前用户已绑定的所有 South Plus UID。"""
        account = event.get_sender_id()
        platform = get_event_platform(event)
        users = self.store.list_for_account(account, platform)
        if not users:
            yield event.plain_result("当前账号尚未绑定任何 UID。请用 /splogin 登录。")
            return
        lines = ["已绑定 UID："]
        for u in users:
            marker = "★" if u.is_active else " "
            lines.append(f"{marker} {u.sp_uid}")
        lines.append("★ 表示当前激活账号；/spswitch <uid> 切换。")
        yield event.plain_result("\n".join(lines))

    @filter.command("spswitch", alias={"sp切换"})
    async def sp_switch(self, event: AstrMessageEvent, uid: str):
        """切换激活账号到指定 UID。"""
        uid = uid.strip()
        if not uid:
            yield event.plain_result("用法：/spswitch <uid>")
            return
        account = event.get_sender_id()
        platform = get_event_platform(event)
        if not self.store.switch_active(account, platform, uid):
            yield event.plain_result(
                f"UID {uid} 不在你的绑定列表里。/spuidlist 查看已绑定 UID。"
            )
            return
        yield event.plain_result(f"已切换激活账号为 UID {uid}。")

    @filter.command("spdelete", alias={"sp删除"})
    async def sp_delete(self, event: AstrMessageEvent, uid: str):
        """删除当前用户绑定的某个 UID。"""
        uid = uid.strip()
        if not uid:
            yield event.plain_result("用法：/spdelete <uid>")
            return
        account = event.get_sender_id()
        if not self.store.delete_account(account, uid):
            yield event.plain_result(f"UID {uid} 不在你的绑定列表里，无法删除。")
            return
        yield event.plain_result(f"已删除 UID {uid} 的绑定。")

    @filter.command("spbindcookie", alias={"sp绑定"})
    async def sp_bind_cookie(self, event: AstrMessageEvent, cookie: str):
        """直接用 Cookie 绑定一个 UID（管理员用，给已经登录过的会话续命）。"""
        cookie = cookie.strip()
        if not cookie:
            yield event.plain_result("用法：/spbindcookie <cookie>")
            return
        try:
            refreshed_cookie = self.client.check_cookie(cookie)
        except SouthPlusLoginError as exc:
            yield event.plain_result(f"Cookie 检查失败：{exc}")
            return
        try:
            profile = await asyncio.to_thread(
                self.profile_client.fetch, refreshed_cookie
            )
        except SouthPlusProfileError as exc:
            yield event.plain_result(f"无法读取该 Cookie 对应的账户资料：{exc}")
            return
        if not profile.uid:
            yield event.plain_result("无法从该 Cookie 中识别出 UID，绑定失败。")
            return
        result = self.store.add_or_update(
            sp_uid=profile.uid,
            account=event.get_sender_id(),
            platform=get_event_platform(event),
            cookie=refreshed_cookie,
        )
        yield event.plain_result(
            format_add_account_result(
                result,
                profile,
                auto_checkin_hint=self.config_snapshot.auto_checkin_enabled,
            )
        )

    # ------------------------------------------------------------------
    # 资料卡片
    # ------------------------------------------------------------------

    @filter.command("spprofile", alias={"sp资料"})
    async def sp_profile(self, event: AstrMessageEvent):
        """抓取激活账号的资料并渲染成卡片图。"""
        active = self.store.get_active(event.get_sender_id(), get_event_platform(event))
        if not active or not active.cookie:
            yield event.plain_result(
                "当前没有激活的 South Plus 账号。请用 /splogin 登录。"
            )
            return
        try:
            profile = await asyncio.to_thread(self.profile_client.fetch, active.cookie)
        except SouthPlusProfileError as exc:
            yield event.plain_result(f"获取资料失败：{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            plugin_logger.exception("spprofile 抓取异常")
            yield event.plain_result(f"获取资料失败：{exc}")
            return

        # 用同一个代理通道拉头像字节，避免渲染层独立去网络（拿不到代理）。
        avatar_bytes = await asyncio.to_thread(
            self.profile_client.fetch_avatar, profile.avatar_url
        )
        try:
            png_bytes = await render_user_card(
                profile, avatar_bytes=avatar_bytes, season=season_name()
            )
        except Exception as exc:  # noqa: BLE001
            plugin_logger.exception("spprofile 卡片渲染失败")
            yield event.plain_result(f"卡片渲染失败：{exc}")
            return

        # AstrBot 4.25 的 image_result 只接路径，把 PNG 落盘到临时文件。
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            tmp.write(png_bytes)
            tmp.flush()
        finally:
            tmp.close()
        yield event.image_result(str(Path(tmp.name)))

    # ------------------------------------------------------------------
    # 社区签到
    # ------------------------------------------------------------------

    @filter.command("spcheckin", alias={"sp签到"})
    async def sp_checkin(self, event: AstrMessageEvent):
        """对当前激活账号执行日签 + 周签。"""
        active = self.store.get_active(event.get_sender_id(), get_event_platform(event))
        if not active or not active.cookie:
            yield event.plain_result(
                "当前没有激活的 South Plus 账号。请用 /splogin 登录。"
            )
            return

        today = current_local_date()
        this_week = current_iso_week()
        sp_uid = active.sp_uid

        daily_skip = self.checkin_store.is_already_done(
            sp_uid=sp_uid,
            task_key=CHECKIN_TASK_KEY_DAILY,
            period_key=today,
        )
        weekly_skip = self.checkin_store.is_already_done(
            sp_uid=sp_uid,
            task_key=CHECKIN_TASK_KEY_WEEKLY,
            period_key=this_week,
        )

        daily_result: CheckinTaskResult | None = None
        weekly_result: CheckinTaskResult | None = None

        if not daily_skip and not weekly_skip:
            report: CheckinReport = await asyncio.to_thread(
                self.checkin_client.checkin, active.cookie
            )
            daily_result = report.daily
            weekly_result = report.weekly
        elif not daily_skip:
            daily_result = await asyncio.to_thread(
                self.checkin_client.checkin_daily, active.cookie
            )
        elif not weekly_skip:
            weekly_result = await asyncio.to_thread(
                self.checkin_client.checkin_weekly, active.cookie
            )

        if daily_result is not None:
            self.checkin_store.record(
                sp_uid=sp_uid,
                task_key=CHECKIN_TASK_KEY_DAILY,
                period_key=today,
                status=daily_result.status.value,
                message=daily_result.message,
                error=daily_result.error,
            )
        if weekly_result is not None:
            self.checkin_store.record(
                sp_uid=sp_uid,
                task_key=CHECKIN_TASK_KEY_WEEKLY,
                period_key=this_week,
                status=weekly_result.status.value,
                message=weekly_result.message,
                error=weekly_result.error,
            )

        yield event.plain_result(
            format_checkin_response(
                uid=sp_uid,
                today=today,
                this_week_label=current_iso_week_label(),
                fresh_daily=daily_result,
                fresh_weekly=weekly_result,
            )
        )

    # ------------------------------------------------------------------
    # 签到订阅
    # ------------------------------------------------------------------

    @filter.command("spsubcheckin", alias={"sp订阅签到"})
    async def sp_sub_checkin(self, event: AstrMessageEvent):
        """订阅当前会话的自动签到汇报（仅当前账号）。"""
        umo = event.unified_msg_origin
        account = event.get_sender_id()
        params = {"mode": "session", "account": account}
        self.scheduler.subscribe(
            umo,
            task_key=CHECKIN_TASK_KEY_SESSION,
            cron=self.config_snapshot.auto_checkin_cron,
            params=params,
        )
        yield event.plain_result(
            _checkin_report_subscribed_message(_CHECKIN_REPORT_SCOPE_CURRENT)
        )

    @filter.command("spunsubcheckin", alias={"sp取消签到"})
    async def sp_unsub_checkin(self, event: AstrMessageEvent):
        """取消当前会话的自动签到汇报订阅。"""
        umo = event.unified_msg_origin
        account = event.get_sender_id()
        params = {"mode": "session", "account": account}
        if self.scheduler.is_subscribed(umo, CHECKIN_TASK_KEY_SESSION, params):
            self.scheduler.unsubscribe(umo, CHECKIN_TASK_KEY_SESSION, params)
            yield event.plain_result(
                _checkin_report_unsubscribed_message(_CHECKIN_REPORT_SCOPE_CURRENT)
            )
        else:
            yield event.plain_result(
                _checkin_report_not_subscribed_message(_CHECKIN_REPORT_SCOPE_CURRENT)
            )

    @filter.command("spcheckinallsub", alias={"sp全局签到订阅"})
    @filter.permission_type(PermissionType.ADMIN)
    async def sp_checkin_all_sub_toggle(self, event: AstrMessageEvent):
        """管理员：切换当前会话的全部账号签到汇报订阅。"""
        umo = event.unified_msg_origin
        params = {"mode": "all"}
        task_key = CHECKIN_TASK_KEY_ALL
        if self.scheduler.is_subscribed(umo, task_key, params):
            self.scheduler.unsubscribe(umo, task_key, params)
            yield event.plain_result(
                _checkin_report_unsubscribed_message(_CHECKIN_REPORT_SCOPE_ALL)
            )
            return
        self.scheduler.subscribe(
            umo,
            task_key=task_key,
            cron=self.config_snapshot.auto_checkin_cron,
            params=params,
        )
        yield event.plain_result(
            _checkin_report_subscribed_message(_CHECKIN_REPORT_SCOPE_ALL)
        )

    @filter.command("spallcheckin", alias={"sp全体签到"})
    @filter.permission_type(PermissionType.ADMIN)
    async def sp_all_checkin(self, event: AstrMessageEvent):
        """管理员：立即执行全部绑定账号签到。"""
        text = await self.scheduler.run_all_checkins()
        yield event.plain_result(text)

    @filter.command("spautocheckin", alias={"sp自动签到"})
    async def sp_set_auto_checkin(self, event: AstrMessageEvent):
        """切换当前激活账号的自动签到开关。"""
        account = event.get_sender_id()
        platform = event.get_platform_name()
        user = self.store.get_active(account, platform)
        if user is None:
            yield event.plain_result("当前未绑定南+ 账号，请先用 /splogin 登录。")
            return

        enabled = not user.auto_checkin
        self.store.set_auto_checkin(user.sp_uid, enabled)
        status = "开启" if enabled else "关闭"
        yield event.plain_result(f"账号 {user.sp_uid} 的自动签到已{status}。")

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    @filter.command("spcleanup", alias={"sp清理"})
    @filter.permission_type(PermissionType.ADMIN)
    async def sp_cleanup(self, event: AstrMessageEvent):
        """管理员：清理退群/非好友用户的绑定数据。"""
        from .src.core.platform_adapter import NapCatMembershipAdapter

        adapter = NapCatMembershipAdapter(self.context)
        users = self.store.list_all()
        stale_uids: set[str] = set()

        for u in users:
            try:
                is_friend = await adapter.is_friend(u.account, u.platform)
            except Exception as exc:
                plugin_logger.warning(
                    f"sp清理 is_friend 异常 account={u.account}: {exc}"
                )
                continue

            if is_friend is False:
                stale_uids.add(u.sp_uid)

        if stale_uids:
            keep_uids = {u.sp_uid for u in users} - stale_uids
            for sp_uid in stale_uids:
                self.user_group_store.delete_by_user(sp_uid)
            self.store.delete_stale(keep_uids)

        yield event.plain_result(
            f"清理完成。检测了 {len(users)} 个用户，"
            f"清理了 {len(stale_uids)} 个退群/非好友用户。"
        )

    # ------------------------------------------------------------------
    # 登录回调（auth server worker 线程调用）
    # ------------------------------------------------------------------

    async def _expire_login_later(self, session: CredentialSession) -> None:
        ttl = max(1, int(session.expires_at - time.time()))
        try:
            await asyncio.sleep(ttl)
        except asyncio.CancelledError:
            return
        expired = self.form_server.expire_session(session.token)
        if expired:
            await self._send_plain(
                expired.unified_msg_origin,
                "South Plus 登录链接已超时，请重新发起 /splogin。",
            )

    def _handle_login_success(
        self,
        session: CredentialSession,
        request: LoginRequest,  # noqa: ARG002 - 接口签名固定
        result: LoginResult,
    ) -> None:
        """auth server 在 worker 线程里调用。

        登录成功的 ``LoginResult`` 只带账号文本（``request.username``，可能
        是用户名/UID/邮箱）和 cookie——拿不到南+ 内部数字 UID。这里立即用
        cookie 拉一次 profile.php 取真实 ``uid`` 和 ``username``，再决定是
        新增 / 刷新 / 拒绝。
        """
        self._cancel_expiry_task(session.token)
        try:
            profile = self.profile_client.fetch(result.cookie)
        except SouthPlusProfileError as exc:
            plugin_logger.warning(f"登录成功但 profile 抓取失败：{exc}")
            self._notify_from_thread(
                session.unified_msg_origin,
                f"登录成功，但抓取账户资料失败：{exc}\n请稍后用 /spbindcookie 重试。",
            )
            return
        except Exception as exc:  # noqa: BLE001
            plugin_logger.exception("登录成功后 profile 抓取异常")
            self._notify_from_thread(
                session.unified_msg_origin,
                f"登录成功，但读取资料异常：{exc}",
            )
            return

        if not profile.uid:
            self._notify_from_thread(
                session.unified_msg_origin,
                "登录成功，但无法识别出 UID，无法保存账号。请稍后再试。",
            )
            return

        add_result = self.store.add_or_update(
            sp_uid=profile.uid,
            account=session.user_key,
            platform=session.platform,
            cookie=result.cookie,
        )
        self._notify_from_thread(
            session.unified_msg_origin,
            format_add_account_result(
                add_result,
                profile,
                auto_checkin_hint=self.config_snapshot.auto_checkin_enabled,
            ),
        )

    def _cancel_expiry_task(self, token: str) -> None:
        task = self._expiry_tasks.pop(token, None)
        if task:
            self._loop.call_soon_threadsafe(task.cancel)

    def _reload_runtime_config(self) -> None:
        """把当前配置同步到运行态调度器和持久化订阅。"""
        self.config_manager = PluginConfigManager(self.config)
        self.config_snapshot = self.config_manager.snapshot()
        self.scheduler.reload_config(
            cron=self.config_snapshot.auto_checkin_cron,
            concurrency=self.config_snapshot.auto_checkin_concurrency,
        )

    def _notify_from_thread(self, unified_msg_origin: str, text: str) -> None:
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._send_plain(unified_msg_origin, text))
        )

    async def _send_plain(self, unified_msg_origin: str, text: str) -> None:
        await self.context.send_message(
            unified_msg_origin, MessageChain().message(text)
        )

    async def terminate(self) -> None:
        self.scheduler.stop()
        for task in self._expiry_tasks.values():
            task.cancel()
        self._expiry_tasks.clear()
        self.form_server.shutdown()
        plugin_logger.info("South Plus plugin terminated.")
