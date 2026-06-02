from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from quart import jsonify, request

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star

from .src.southplus.api import (
    LoginRequest,
    LoginResult,
    SouthPlusClient,
    SouthPlusLoginError,
    SouthPlusProfileClient,
    SouthPlusProfileError,
)
from .src.core.auth_server import CredentialFormServer
from .src.core.config_manager import PluginConfigManager
from .src.core.data_source import CredentialStore
from .src.core.datamodels import CredentialSession
from .src.core.logger import plugin_logger
from .src.core.user_card_render import render_user_card
from .src.shared.constants import PLUGIN_NAME


class SouthPlusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self._loop = asyncio.get_event_loop()
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self.config_manager = PluginConfigManager(self.config)
        self.config_snapshot = self.config_manager.snapshot()
        self.store = CredentialStore(
            self.config_snapshot.database_path,
            cookie_encryption_key=self.config_snapshot.cookie_encryption_key,
        )
        self.client = SouthPlusClient(
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

    @filter.command("splogin")
    async def sp_login(self, event: AstrMessageEvent):
        """生成一次性网页登录链接。"""
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

    @filter.command("spstatus")
    async def sp_status(self, event: AstrMessageEvent):
        """查看当前用户的绑定状态。"""
        credential = self.store.get(event.get_sender_id())
        if not credential:
            yield event.plain_result("当前账号尚未绑定 South Plus 凭证。")
            return
        yield event.plain_result(
            "South Plus 凭证状态：\n"
            f"账号：{credential.username or '(未记录)'}\n"
            f"启用：{'是' if credential.enabled else '否'}\n"
            f"定时：{credential.schedule_time or '(未设置)'}\n"
            f"上次结果：{credential.last_status or '(无)'} {credential.last_message}"
        )

    @filter.command("spunbind")
    async def sp_unbind(self, event: AstrMessageEvent):
        """删除当前用户凭证。"""
        self.store.delete(event.get_sender_id())
        yield event.plain_result("已删除当前用户的 South Plus 凭证。")

    @filter.command("spbindcookie")
    async def sp_bind_cookie(self, event: AstrMessageEvent, cookie: str):
        """直接绑定 Cookie。"""
        try:
            refreshed_cookie = self.client.check_cookie(cookie)
        except SouthPlusLoginError as exc:
            yield event.plain_result(f"Cookie 检查失败：{exc}")
            return
        self.store.upsert_credential(
            user_key=event.get_sender_id(),
            unified_msg_origin=event.unified_msg_origin,
            username="",
            cookie=refreshed_cookie,
        )
        yield event.plain_result("Cookie 已保存并通过登录态检查。")

    @filter.command("spprofile")
    async def sp_profile(self, event: AstrMessageEvent):
        """抓取并渲染当前用户的 South Plus 资料卡片。"""
        credential = self.store.get(event.get_sender_id())
        if not credential or not credential.cookie:
            yield event.plain_result("未绑定凭证，请先 /splogin")
            return
        try:
            profile_client = SouthPlusProfileClient(
                self.config_snapshot.endpoints,
                http_proxy=self.config_snapshot.http_proxy,
            )
            # httpx 是同步 client；丢到 executor 里跑避免阻塞事件循环。
            profile = await asyncio.to_thread(profile_client.fetch, credential.cookie)
            png_bytes = await asyncio.to_thread(render_user_card, profile)
        except SouthPlusProfileError as exc:
            yield event.plain_result(f"获取资料失败：{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            plugin_logger.exception("spprofile 渲染失败")
            yield event.plain_result(f"获取资料失败：{exc}")
            return

        # AstrBot 4.25 的 image_result 只接路径，把 PNG 落盘到临时文件。
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            tmp.write(png_bytes)
            tmp.flush()
        finally:
            tmp.close()
        yield event.image_result(str(Path(tmp.name)))

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
        request: LoginRequest,
        result: LoginResult,
    ) -> None:
        self._cancel_expiry_task(session.token)
        self.store.upsert_credential(
            user_key=session.user_key,
            unified_msg_origin=session.unified_msg_origin,
            username=result.username or request.username,
            cookie=result.cookie,
        )
        self.store.update_run_result(
            session.user_key, status="login_ok", message=result.message
        )
        self._notify_from_thread(
            session.unified_msg_origin, "South Plus 登录成功，Cookie 已保存。"
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

    def _register_page_apis(self, context: Context) -> None:
        context.register_web_api(
            f"/{PLUGIN_NAME}/credentials",
            self.api_list_credentials,
            ["GET"],
            "List credentials",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/credentials",
            self.api_save_credential,
            ["POST"],
            "Save credential",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/credentials/delete",
            self.api_delete_credential,
            ["POST"],
            "Delete credential",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/credentials/toggle",
            self.api_toggle_credential,
            ["POST"],
            "Toggle credential",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/credentials/schedule",
            self.api_schedule_credential,
            ["POST"],
            "Update schedule",
        )

    async def api_list_credentials(self):
        return jsonify(
            {
                "ok": True,
                "items": [item.to_public_dict() for item in self.store.list_all()],
            }
        )

    async def api_save_credential(self):
        payload = await request.get_json(force=True)
        self.store.upsert_credential(
            user_key=str(payload.get("user_key", "")).strip(),
            unified_msg_origin=str(payload.get("unified_msg_origin", "")).strip(),
            username=str(payload.get("username", "")).strip(),
            cookie=str(payload.get("cookie", "")).strip(),
            enabled=bool(payload.get("enabled", True)),
            schedule_time=str(payload.get("schedule_time", "")).strip(),
        )
        return jsonify({"ok": True})

    async def api_delete_credential(self):
        payload = await request.get_json(force=True)
        self.store.delete(str(payload.get("user_key", "")).strip())
        return jsonify({"ok": True})

    async def api_toggle_credential(self):
        payload = await request.get_json(force=True)
        self.store.set_enabled(
            str(payload.get("user_key", "")).strip(),
            bool(payload.get("enabled", True)),
        )
        return jsonify({"ok": True})

    async def api_schedule_credential(self):
        payload = await request.get_json(force=True)
        self.store.set_schedule(
            str(payload.get("user_key", "")).strip(),
            str(payload.get("schedule_time", "")).strip(),
        )
        return jsonify({"ok": True})

    async def terminate(self) -> None:
        for task in self._expiry_tasks.values():
            task.cancel()
        self._expiry_tasks.clear()
        self.form_server.shutdown()
        plugin_logger.info("South Plus plugin terminated.")
