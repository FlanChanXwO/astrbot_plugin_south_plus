from __future__ import annotations

import html
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, unquote, urlparse

from ..southplus.api import (
    LoginRequest,
    LoginResult,
    SouthPlusLoginApi,
    SouthPlusLoginAttempt,
    SouthPlusLoginError,
)
from ..utils import expires_at_after, generate_token
from .datamodels import AuthServerConfig, CredentialSession
from ..utils.logger import plugin_logger

LoginSuccessCallback = Callable[[CredentialSession, LoginRequest, LoginResult], None]

# 模板与静态资源根目录（项目根 / templates、项目根 / assets）。
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"
_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
_TEMPLATE_CACHE: dict[str, Template] = {}
_ASSET_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")

# 静态资源后缀 → MIME 类型映射。
_ASSET_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def _render(template_name: str, **mapping: str) -> str:
    """从 templates/ 读取模板，按 string.Template 语法替换占位符。模板首次加载后缓存。"""
    template = _TEMPLATE_CACHE.get(template_name)
    if template is None:
        path = _TEMPLATE_DIR / template_name
        template = Template(path.read_text(encoding="utf-8"))
        _TEMPLATE_CACHE[template_name] = template
    return template.substitute(**mapping)


def _asset_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return _ASSET_MIME.get(suffix, "application/octet-stream")


class LoginState(str, Enum):
    AWAITING = "awaiting"
    SUBMITTING = "submitting"
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class _LoginEntry:
    session: CredentialSession
    attempt: SouthPlusLoginAttempt | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    state: LoginState = LoginState.AWAITING
    error: str = ""


class CredentialFormServer:
    def __init__(
        self,
        *,
        config: AuthServerConfig,
        client: SouthPlusLoginApi,
        on_login_success: LoginSuccessCallback,
    ) -> None:
        self.config = config
        self.client = client
        self.on_login_success = on_login_success
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._entries: dict[str, _LoginEntry] = {}
        self._lock = threading.RLock()

    @property
    def actual_port(self) -> int:
        if not self._server:
            return self.config.listen_port
        return int(self._server.server_address[1])

    def ensure_started(self) -> None:
        with self._lock:
            if self._server:
                return
            handler = self._make_handler()
            self._server = ThreadingHTTPServer(
                (self.config.listen_host, self.config.listen_port), handler
            )
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="southplus-login-form-server",
                daemon=True,
            )
            self._thread.start()
            plugin_logger.info(
                f"Login form server listening on {self.config.listen_host}:{self.actual_port}"
            )

    def shutdown(self) -> None:
        with self._lock:
            server = self._server
            entries = list(self._entries.values())
            self._server = None
            self._entries.clear()
        for entry in entries:
            self._close_entry(entry)
        if server:
            server.shutdown()
            server.server_close()

    def create_session(
        self,
        *,
        user_key: str,
        unified_msg_origin: str,
        platform: str = "",
    ) -> CredentialSession:
        self.ensure_started()
        token = generate_token()
        session = CredentialSession(
            token=token,
            user_key=user_key,
            unified_msg_origin=unified_msg_origin,
            platform=platform,
            expires_at=expires_at_after(self.config.token_ttl_seconds),
        )
        entry = _LoginEntry(session=session)
        with self._lock:
            self._entries[token] = entry
        return session

    def build_url(self, token: str) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if base:
            return f"{base}/login/{token}"
        return f"http://{self.config.listen_host}:{self.actual_port}/login/{token}"

    def expire_session(self, token: str) -> CredentialSession | None:
        entry = self._take_entry(token)
        if not entry:
            return None
        with entry.lock:
            if entry.state == LoginState.AWAITING:
                entry.state = LoginState.EXPIRED
            self._close_entry(entry)
        return entry.session

    def cancel_session(self, token: str) -> CredentialSession | None:
        entry = self._take_entry(token)
        if not entry:
            return None
        with entry.lock:
            entry.state = LoginState.CANCELLED
            self._close_entry(entry)
        return entry.session

    def _take_entry(self, token: str) -> _LoginEntry | None:
        with self._lock:
            return self._entries.pop(token, None)

    def _peek_entry(self, token: str) -> _LoginEntry | None:
        with self._lock:
            entry = self._entries.get(token)
        if not entry:
            return None
        if entry.session.expires_at <= time.time():
            self._take_entry(token)
            with entry.lock:
                entry.state = LoginState.EXPIRED
                self._close_entry(entry)
            return None
        return entry

    def _close_entry(self, entry: _LoginEntry) -> None:
        if entry.attempt:
            try:
                entry.attempt.close()
            except Exception as exc:  # noqa: BLE001 - 释放资源出错只记日志
                plugin_logger.warning(f"关闭 SouthPlus 登录尝试失败：{exc}")
            entry.attempt = None

    def _ensure_attempt(self, entry: _LoginEntry) -> SouthPlusLoginAttempt:
        if entry.attempt is None:
            entry.attempt = self.client.new_attempt()
        return entry.attempt

    def handle_captcha(self, token: str) -> tuple[bytes, str] | None:
        entry = self._peek_entry(token)
        if not entry:
            return None
        with entry.lock:
            if entry.state != LoginState.AWAITING:
                return None
            attempt = self._ensure_attempt(entry)
            payload = attempt.fetch_captcha()
        return payload.body, payload.content_type

    def handle_submit(
        self, token: str, username: str, password: str, captcha: str
    ) -> tuple[bool, str]:
        if not username or not password:
            return False, "账号和密码不能为空。"
        entry = self._peek_entry(token)
        if not entry:
            return False, "登录链接已过期或不存在，请重新发起 /splogin。"
        with entry.lock:
            if entry.state != LoginState.AWAITING:
                return False, "登录请求已提交，请勿重复提交。"
            entry.state = LoginState.SUBMITTING
            attempt = self._ensure_attempt(entry)
            request = LoginRequest(
                username=username, password=password, captcha=captcha
            )
            try:
                result = attempt.submit(request)
            except SouthPlusLoginError as exc:
                entry.state = LoginState.AWAITING
                entry.error = str(exc)
                return False, str(exc)
            except Exception as exc:  # noqa: BLE001
                entry.state = LoginState.AWAITING
                entry.error = f"南+ 登录请求异常：{exc}"
                plugin_logger.exception("南+ 登录请求异常")
                return False, entry.error
            entry.state = LoginState.DONE
        try:
            self.on_login_success(entry.session, request, result)
        finally:
            self._take_entry(token)
            with entry.lock:
                self._close_entry(entry)
        return True, "登录成功，Cookie 已保存。可以关闭此页面。"

    def handle_asset(self, filename: str) -> tuple[bytes, str] | None:
        """读取 assets/ 下的静态文件，拒绝路径穿越。"""
        # 防御路径穿越：解码后再二次校验。
        try:
            decoded = unquote(filename)
        except Exception:  # noqa: BLE001
            return None
        if not decoded or not _ASSET_NAME_OK.match(decoded):
            return None
        target = (_ASSETS_DIR / decoded).resolve()
        try:
            target.relative_to(_ASSETS_DIR.resolve())
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target.read_bytes(), _asset_mime(decoded)

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class LoginFormHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 父类签名固定
                del format, args
                return

            def do_GET(self) -> None:
                kind, value = _route(self.path)
                if kind == "login":
                    entry = outer._peek_entry(value)
                    if not entry:
                        self._send_html(HTTPStatus.GONE, _render("expired.html"))
                        return
                    self._send_html(
                        HTTPStatus.OK,
                        _render("login.html", token=html.escape(value, quote=True)),
                    )
                    return
                if kind == "captcha":
                    try:
                        payload = outer.handle_captcha(value)
                    except SouthPlusLoginError as exc:
                        self._send_json(
                            HTTPStatus.BAD_GATEWAY, {"ok": False, "message": str(exc)}
                        )
                        return
                    except Exception as exc:  # noqa: BLE001
                        plugin_logger.exception("拉取验证码失败")
                        self._send_json(
                            HTTPStatus.BAD_GATEWAY,
                            {"ok": False, "message": f"拉取验证码失败：{exc}"},
                        )
                        return
                    if not payload:
                        self._send_json(
                            HTTPStatus.GONE, {"ok": False, "message": "链接已过期。"}
                        )
                        return
                    body, content_type = payload
                    self._send_bytes(HTTPStatus.OK, content_type, body)
                    return
                if kind == "asset":
                    asset = outer.handle_asset(value)
                    if not asset:
                        self._send_html(HTTPStatus.NOT_FOUND, _render("404.html"))
                        return
                    body, content_type = asset
                    self._send_bytes(HTTPStatus.OK, content_type, body)
                    return
                self._send_html(HTTPStatus.NOT_FOUND, _render("404.html"))

            def do_POST(self) -> None:
                kind, value = _route(self.path)
                body = self._read_body()
                if kind == "login":
                    fields = _parse_fields(self.headers.get("Content-Type", ""), body)
                    username = fields.get("username", "")
                    password = fields.get("password", "")
                    captcha = fields.get("captcha", "")
                    ok, message = outer.handle_submit(
                        value, username, password, captcha
                    )
                    self._send_json(
                        HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST,
                        {"ok": ok, "message": message},
                    )
                    return
                if kind == "cancel":
                    cancelled = outer.cancel_session(value)
                    if cancelled is None:
                        self._send_json(
                            HTTPStatus.GONE,
                            {"ok": False, "message": "链接已不存在或已结束。"},
                        )
                        return
                    self._send_json(
                        HTTPStatus.OK, {"ok": True, "message": "已取消登录。"}
                    )
                    return
                self._send_html(HTTPStatus.NOT_FOUND, _render("404.html"))

            def _read_body(self) -> bytes:
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                if length <= 0:
                    return b""
                return self.rfile.read(length)

            def _send_bytes(
                self, status: HTTPStatus, content_type: str, body: bytes
            ) -> None:
                self.send_response(int(status))
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, status: HTTPStatus, content: str) -> None:
                self._send_bytes(
                    status, "text/html; charset=utf-8", content.encode("utf-8")
                )

            def _send_json(self, status: HTTPStatus, data: dict[str, object]) -> None:
                self._send_bytes(
                    status,
                    "application/json; charset=utf-8",
                    json.dumps(data, ensure_ascii=False).encode("utf-8"),
                )

        return LoginFormHandler


def _route(path: str) -> tuple[str, str]:
    parsed = urlparse(path)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2:
        if parts[0] in {"login", "captcha", "cancel"}:
            return parts[0], parts[1]
        if parts[0] == "assets":
            return "asset", parts[1]
    return "", ""


def _parse_fields(content_type: str, body: bytes) -> dict[str, str]:
    raw = body.decode("utf-8", errors="replace")
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct == "application/json":
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    form = parse_qs(raw)
    return {key: (values[0] if values else "").strip() for key, values in form.items()}
