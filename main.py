from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from quart import jsonify, request

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star

from .src.core.auth_server import CredentialFormServer
from .src.core.config_manager import PluginConfigManager
from .src.core.data_source import AccountStore
from .src.core.datamodels import (
    AddAccountResult,
    AddAccountStatus,
    CredentialSession,
)
from .src.core.logger import plugin_logger
from .src.core.user_card_render import render_user_card
from .src.shared.constants import PLUGIN_NAME
from .src.southplus.api import (
    LoginRequest,
    LoginResult,
    SouthPlusClient,
    SouthPlusLoginError,
    SouthPlusProfileClient,
    SouthPlusProfileError,
    UserProfile,
)


class SouthPlusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self._loop = asyncio.get_event_loop()
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self.config_manager = PluginConfigManager(self.config)
        self.config_snapshot = self.config_manager.snapshot()
        self.store = AccountStore(
            self.config_snapshot.database_path,
            cookie_encryption_key=self.config_snapshot.cookie_encryption_key,
        )
        self.client = SouthPlusClient(
            self.config_snapshot.endpoints,
            http_proxy=self.config_snapshot.http_proxy,
        )
        self.profile_client = SouthPlusProfileClient(
            self.config_snapshot.endpoints,
            http_proxy=self.config_snapshot.http_proxy,
        )
        self.form_server = CredentialFormServer(
            config=self.config_snapshot.auth_server,
            client=self.client,
            on_login_success=self._handle_login_success,
        )
        self._register_page_apis(context)
        plugin_logger.info("South Plus plugin initialized.")

    # ------------------------------------------------------------------
    # 登录链接
    # ------------------------------------------------------------------

    @filter.command("splogin")
    async def sp_login(self, event: AstrMessageEvent):
        """生成一次性网页登录链接。每次登录成功会自动新增/刷新一条 UID 绑定。"""
        session = self.form_server.create_session(
            user_key=event.get_sender_id(),
            unified_msg_origin=event.unified_msg_origin,
        )
        self._expiry_tasks[session.token] = asyncio.create_task(
            self._expire_login_later(session)
        )
        url = self.form_server.build_url(session.token)
        ttl = self.config_snapshot.auth_server.token_ttl_seconds
        minutes = max(1, ttl // 60)
        yield event.plain_result(
            f"请在 {minutes} 分钟内打开并提交登录表单：\n{url}\n"
            "页面会代理拉取站点验证码，请手动填写。"
        )

    # ------------------------------------------------------------------
    # 账号管理命令
    # ------------------------------------------------------------------

    @filter.command("spstatus")
    async def sp_status(self, event: AstrMessageEvent):
        """查看当前激活账号。"""
        user_key = event.get_sender_id()
        active = self.store.get_active(user_key)
        accounts = self.store.list_for_user(user_key)
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
            "当前激活账号：\n"
            f"用户名：{active.username or '(未记录)'}\n"
            f"UID：{active.uid}\n"
            f"绑定总数：{len(accounts)}\n"
            f"上次结果：{active.last_status or '(无)'} {active.last_message}"
        )

    @filter.command("spuidlist")
    async def sp_uid_list(self, event: AstrMessageEvent):
        """列出当前用户已绑定的所有 South Plus UID。"""
        accounts = self.store.list_for_user(event.get_sender_id())
        if not accounts:
            yield event.plain_result("当前账号尚未绑定任何 UID。请用 /splogin 登录。")
            return
        lines = ["已绑定 UID："]
        for acc in accounts:
            marker = "★" if acc.is_active else " "
            lines.append(f"{marker} {acc.uid}  {acc.username or '(未记录)'}")
        lines.append("★ 表示当前激活账号；/spswitch <uid> 切换。")
        yield event.plain_result("\n".join(lines))

    @filter.command("spswitch")
    async def sp_switch(self, event: AstrMessageEvent, uid: str):
        """切换激活账号到指定 UID。"""
        uid = uid.strip()
        if not uid:
            yield event.plain_result("用法：/spswitch <uid>")
            return
        user_key = event.get_sender_id()
        if not self.store.switch_active(user_key, uid):
            yield event.plain_result(
                f"UID {uid} 不在你的绑定列表里。/spuidlist 查看已绑定 UID。"
            )
            return
        active = self.store.get_active(user_key)
        if active:
            yield event.plain_result(
                f"已切换为：{active.username or '(未记录)'}（UID: {active.uid}）"
            )
        else:
            yield event.plain_result(f"已切换激活账号为 UID {uid}。")

    @filter.command("spdelete")
    async def sp_delete(self, event: AstrMessageEvent, uid: str):
        """删除当前用户绑定的某个 UID。"""
        uid = uid.strip()
        if not uid:
            yield event.plain_result("用法：/spdelete <uid>")
            return
        user_key = event.get_sender_id()
        if not self.store.delete_account(user_key, uid):
            yield event.plain_result(f"UID {uid} 不在你的绑定列表里，无法删除。")
            return
        yield event.plain_result(f"已删除 UID {uid} 的绑定。")

    @filter.command("spbindcookie")
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
            uid=profile.uid,
            user_key=event.get_sender_id(),
            unified_msg_origin=event.unified_msg_origin,
            username=profile.username,
            cookie=refreshed_cookie,
        )
        yield event.plain_result(_format_add_result(result, profile))

    # ------------------------------------------------------------------
    # 资料卡片
    # ------------------------------------------------------------------

    @filter.command("spprofile")
    async def sp_profile(self, event: AstrMessageEvent):
        """抓取激活账号的资料并渲染成卡片图。"""
        active = self.store.get_active(event.get_sender_id())
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
            png_bytes = await asyncio.to_thread(
                render_user_card, profile, avatar_bytes=avatar_bytes
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
            uid=profile.uid,
            user_key=session.user_key,
            unified_msg_origin=session.unified_msg_origin,
            username=profile.username,
            cookie=result.cookie,
        )
        if add_result.status != AddAccountStatus.OWNED_BY_OTHER:
            self.store.update_run_result(
                profile.uid, status="login_ok", message=result.message
            )
        self._notify_from_thread(
            session.unified_msg_origin, _format_add_result(add_result, profile)
        )

    def _cancel_expiry_task(self, token: str) -> None:
        task = self._expiry_tasks.pop(token, None)
        if task:
            self._loop.call_soon_threadsafe(task.cancel)

    def _notify_from_thread(self, unified_msg_origin: str, text: str) -> None:
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._send_plain(unified_msg_origin, text))
        )

    async def _send_plain(self, unified_msg_origin: str, text: str) -> None:
        await self.context.send_message(
            unified_msg_origin, MessageChain().message(text)
        )

    # ------------------------------------------------------------------
    # Dashboard Web API
    # ------------------------------------------------------------------

    def _register_page_apis(self, context: Context) -> None:
        context.register_web_api(
            f"/{PLUGIN_NAME}/accounts",
            self.api_list_accounts,
            ["GET"],
            "List accounts",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/accounts/delete",
            self.api_delete_account,
            ["POST"],
            "Delete account",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/accounts/switch",
            self.api_switch_account,
            ["POST"],
            "Switch active account",
        )

    async def api_list_accounts(self):
        return jsonify(
            {
                "ok": True,
                "items": [item.to_public_dict() for item in self.store.list_all()],
            }
        )

    async def api_delete_account(self):
        payload = await request.get_json(force=True)
        user_key = str(payload.get("user_key", "")).strip()
        uid = str(payload.get("uid", "")).strip()
        if not user_key or not uid:
            return jsonify({"ok": False, "message": "user_key 与 uid 必填"}), 400
        ok = self.store.delete_account(user_key, uid)
        return jsonify({"ok": ok})

    async def api_switch_account(self):
        payload = await request.get_json(force=True)
        user_key = str(payload.get("user_key", "")).strip()
        uid = str(payload.get("uid", "")).strip()
        if not user_key or not uid:
            return jsonify({"ok": False, "message": "user_key 与 uid 必填"}), 400
        ok = self.store.switch_active(user_key, uid)
        return jsonify({"ok": ok})

    async def terminate(self) -> None:
        for task in self._expiry_tasks.values():
            task.cancel()
        self._expiry_tasks.clear()
        self.form_server.shutdown()
        plugin_logger.info("South Plus plugin terminated.")


def _format_add_result(result: AddAccountResult, profile: UserProfile) -> str:
    """根据 ``AccountStore.add_or_update`` 的结果给出面向用户的提示文案。"""
    username = profile.username or result.account.username or "(未记录)"
    uid = profile.uid or result.account.uid or "(未知)"
    if result.status is AddAccountStatus.CREATED:
        return f"登录成功：用户名：{username}，id：{uid}"
    if result.status is AddAccountStatus.REFRESHED:
        return (
            f"登录成功（该 UID 已绑定过，已刷新 Cookie 并切换为当前账号）：\n"
            f"用户名：{username}，id：{uid}"
        )
    # OWNED_BY_OTHER
    return (
        f"该 UID（{uid}）已被其他用户绑定，无法绑定。\n"
        "如确需迁移，请联系管理员从数据库删除该 UID 的旧绑定后再试。"
    )
