from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

# 一张 1x1 透明 PNG。
_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000005000100"
    "0d0a2db40000000049454e44ae426082"
)


@dataclass
class MockSouthPlusState:
    base_url: str
    valid_username: str = "alice"
    valid_password: str = "secret123"
    valid_captcha: str = "1234"
    last_login_payload: dict[str, str] = field(default_factory=dict)
    captcha_calls: int = 0
    login_calls: int = 0
    captcha_bytes: bytes = _MIN_PNG


@pytest.fixture()
def mock_southplus() -> Iterator[MockSouthPlusState]:
    state = MockSouthPlusState(base_url="")
    server, thread = _start_mock_server(state)
    host, port = server.server_address[:2]
    state.base_url = f"http://{host}:{port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _start_mock_server(
    state: MockSouthPlusState,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    handler_cls = _make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _make_handler(state: MockSouthPlusState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/login.php":
                body = _LOGIN_PAGE.encode("utf-8")
                self._send(
                    HTTPStatus.OK,
                    "text/html; charset=utf-8",
                    body,
                    set_cookies=["eb9e6_lastvisit=0%090%09%2Flogin.php"],
                )
                return
            if path == "/ck.php":
                state.captcha_calls += 1
                self._send(
                    HTTPStatus.OK, "application/octet-stream", state.captcha_bytes
                )
                return
            if path == "/index.php":
                cookie = self.headers.get("Cookie", "")
                if "eb9e6_winduser" in cookie:
                    self._send(
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        b"<a>\xe9\x80\x80\xe5\x87\xba</a>",
                    )
                else:
                    self._send(
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        b"<a>\xe7\x99\xbb\xe5\xbd\x95</a>",
                    )
                return
            self._send(HTTPStatus.NOT_FOUND, "text/plain", b"")

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/login.php":
                state.login_calls += 1
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8")
                form = {
                    key: (values[0] if values else "")
                    for key, values in parse_qs(raw).items()
                }
                state.last_login_payload = form
                ok = (
                    form.get("pwuser") == state.valid_username
                    and form.get("pwpwd") == state.valid_password
                    and form.get("gdcode") == state.valid_captcha
                )
                if not ok:
                    if form.get("gdcode") != state.valid_captcha:
                        body = "<p>认证码错误</p>".encode("utf-8")
                    else:
                        body = "<p>密码错误</p>".encode("utf-8")
                    self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
                    return
                cookies = [
                    "eb9e6_winduser=alice; path=/; httponly",
                    "eb9e6_winduid=1; path=/; httponly",
                    "eb9e6_windpwd=hash; path=/; httponly",
                ]
                body = "<html>登录成功 退出</html>".encode("utf-8")
                self._send(
                    HTTPStatus.OK, "text/html; charset=utf-8", body, set_cookies=cookies
                )
                return
            self._send(HTTPStatus.NOT_FOUND, "text/plain", b"")

        def _send(
            self,
            status: HTTPStatus,
            content_type: str,
            body: bytes,
            *,
            set_cookies: list[str] | None = None,
        ) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for cookie in set_cookies or []:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

    return _Handler


_LOGIN_PAGE = """<!doctype html>
<html><body>
<form action="/login.php?" method="post" name="login">
  <input type="hidden" name="forward" value="" />
  <input type="hidden" name="jumpurl" value="/index.php" />
  <input type="hidden" name="step" value="2" />
  <input type="text" name="gdcode" />
  <input type="radio" name="lgt" value="0" checked />
  <input type="text" name="pwuser" />
  <input type="password" name="pwpwd" />
  <input type="radio" name="hideid" value="0" checked />
  <input type="radio" name="cktime" value="31536000" checked />
  <input type="submit" name="submit" value="登 录" />
</form>
<a>登录</a>
</body></html>
"""
