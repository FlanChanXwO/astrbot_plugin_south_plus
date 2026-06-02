from __future__ import annotations

import html
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..api.client import SouthPlusClient, SouthPlusLoginAttempt, SouthPlusLoginError
from ..api.models import LoginRequest, LoginResult
from ..utils import expires_at_after, generate_token
from .datamodels import AuthServerConfig, CredentialSession
from .logger import plugin_logger

LoginSuccessCallback = Callable[[CredentialSession, LoginRequest, LoginResult], None]


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
        client: SouthPlusClient,
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
        self, *, user_key: str, unified_msg_origin: str
    ) -> CredentialSession:
        self.ensure_started()
        token = generate_token()
        session = CredentialSession(
            token=token,
            user_key=user_key,
            unified_msg_origin=unified_msg_origin,
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

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class LoginFormHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 父类签名固定
                del format, args
                return

            def do_GET(self) -> None:
                kind, token = _route(self.path)
                if kind == "login":
                    entry = outer._peek_entry(token)
                    if not entry:
                        self._send_html(HTTPStatus.GONE, _expired_page())
                        return
                    seconds_left = max(0, int(entry.session.expires_at - time.time()))
                    self._send_html(HTTPStatus.OK, _form_page(token, seconds_left))
                    return
                if kind == "captcha":
                    try:
                        payload = outer.handle_captcha(token)
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
                self._send_html(
                    HTTPStatus.NOT_FOUND, _message_page("请求的路径不存在。")
                )

            def do_POST(self) -> None:
                kind, token = _route(self.path)
                body = self._read_body()
                if kind == "login":
                    fields = _parse_fields(self.headers.get("Content-Type", ""), body)
                    username = fields.get("username", "")
                    password = fields.get("password", "")
                    captcha = fields.get("captcha", "")
                    ok, message = outer.handle_submit(
                        token, username, password, captcha
                    )
                    self._send_json(
                        HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST,
                        {"ok": ok, "message": message},
                    )
                    return
                if kind == "cancel":
                    cancelled = outer.cancel_session(token)
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
                self._send_html(
                    HTTPStatus.NOT_FOUND, _message_page("请求的路径不存在。")
                )

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
    if len(parts) == 2 and parts[0] in {"login", "captcha", "cancel"}:
        return parts[0], parts[1]
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


def _form_page(token: str, seconds_left: int) -> str:
    safe_token = html.escape(token, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>South Plus 登录</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #1f2937; }}
    main {{ max-width: 460px; }}
    form {{ display: grid; gap: 14px; margin-top: 12px; }}
    label {{ display: grid; gap: 6px; font-weight: 600; }}
    input, button {{ font: inherit; padding: 10px; border-radius: 6px; border: 1px solid #d1d5db; }}
    button {{ cursor: pointer; }}
    button.primary {{ background: #2563eb; color: white; border-color: #2563eb; }}
    button.secondary {{ background: white; color: #374151; }}
    .captcha {{ display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }}
    .captcha img {{ height: 60px; border: 1px solid #d1d5db; border-radius: 6px; background: #f9fafb; }}
    .hint {{ color: #4b5563; line-height: 1.6; }}
    .status {{ margin-top: 14px; padding: 12px; border-radius: 6px; display: none; }}
    .status.ok {{ background: #ecfdf5; color: #065f46; display: block; }}
    .status.err {{ background: #fef2f2; color: #991b1b; display: block; }}
    .actions {{ display: flex; gap: 10px; }}
  </style>
</head>
<body>
  <main>
    <h1>South Plus 登录</h1>
    <p class="hint">链接一次性有效，提交后立即失效。密码只用于本次刷新 Cookie，不会保存。</p>
    <p class="hint">剩余有效期约 {max(seconds_left, 0)} 秒。</p>
    <form id="login-form" autocomplete="off">
      <label>账号<input name="username" required></label>
      <label>密码<input name="password" type="password" required></label>
      <div>
        <div style="font-weight:600; margin-bottom:6px;">认证码</div>
        <div class="captcha">
          <input name="captcha" required>
          <img id="captcha-img" alt="captcha" src="/captcha/{safe_token}">
        </div>
        <p class="hint" style="margin:6px 0 0">点验证码图片可刷新；图片由插件代理拉取。</p>
      </div>
      <div class="actions">
        <button class="primary" type="submit" id="submit-btn">提交</button>
        <button class="secondary" type="button" id="cancel-btn">取消</button>
      </div>
      <div id="status" class="status"></div>
    </form>
  </main>
  <script>
    (function() {{
      const token = "{safe_token}";
      const form = document.getElementById("login-form");
      const status = document.getElementById("status");
      const img = document.getElementById("captcha-img");
      const submitBtn = document.getElementById("submit-btn");
      const cancelBtn = document.getElementById("cancel-btn");

      function setStatus(text, ok) {{
        status.textContent = text;
        status.className = "status " + (ok ? "ok" : "err");
      }}

      function refreshCaptcha() {{
        img.src = "/captcha/" + encodeURIComponent(token) + "?_=" + Date.now();
      }}

      img.addEventListener("click", refreshCaptcha);

      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        submitBtn.disabled = true;
        setStatus("提交中…", true);
        const data = new FormData(form);
        try {{
          const response = await fetch("/login/" + encodeURIComponent(token), {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              username: data.get("username") || "",
              password: data.get("password") || "",
              captcha: data.get("captcha") || "",
            }}),
          }});
          const payload = await response.json();
          setStatus(payload.message || "", payload.ok);
          if (payload.ok) {{
            form.reset();
            submitBtn.disabled = true;
            cancelBtn.disabled = true;
          }} else {{
            submitBtn.disabled = false;
            refreshCaptcha();
          }}
        }} catch (err) {{
          submitBtn.disabled = false;
          setStatus("网络异常：" + err.message, false);
        }}
      }});

      cancelBtn.addEventListener("click", async () => {{
        cancelBtn.disabled = true;
        try {{
          const response = await fetch("/cancel/" + encodeURIComponent(token), {{ method: "POST" }});
          const payload = await response.json();
          setStatus(payload.message || "已取消登录。", payload.ok);
          submitBtn.disabled = true;
        }} catch (err) {{
          cancelBtn.disabled = false;
          setStatus("网络异常：" + err.message, false);
        }}
      }});
    }})();
  </script>
</body>
</html>"""


def _expired_page() -> str:
    return _message_page("链接不存在或已过期。请回到聊天窗口重新发起 /splogin。")


def _message_page(message: str) -> str:
    safe_message = html.escape(message)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>South Plus 登录结果</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; color: #1f2937; }}
  </style>
</head>
<body>
  <p>{safe_message}</p>
</body>
</html>"""
