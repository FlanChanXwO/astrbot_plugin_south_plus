"""profile.php 抓取与解析测试。

用本地 HTTP server 模拟 profile.php 返回，覆盖：成功解析、未登录响应抛错、
字段缺失时回落默认。线上 cookie 失效（用户尚未重新登录）所以这里只能用合
成 HTML 验证 parser 的鲁棒性。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.southplus.api import (
    SouthPlusEndpoints,
    SouthPlusProfileApi,
    SouthPlusProfileError,
    SouthPlusSession,
    UserProfile,
)
from src.southplus.api.profile import parse_profile_html

# --- 合成 HTML --------------------------------------------------------------

_FULL_PROFILE_HTML = """<!doctype html>
<html><head><title>flanchan - South Plus</title></head>
<body>
<div class="profile">
  <img src="https://bbs.south-plus.org/uploadface/avatar/2030219.jpg" alt="头像" />
  <p>用户名: <b>flanchan</b></p>
  <p>数字ID: <span>2030219</span></p>
  <p>个性签名: <i>您还没有设置个性签名</i></p>
  <p>会员头衔: <span>Lv.0</span></p>
  <p>精华: <b>3</b></p>
  <p>发帖: <b>128</b></p>
  <p>HP: <b>50</b></p>
  <p>魄: <b>20</b></p>
  <p>SP币: <b>14 G</b></p>
  <p>LP: <b>7</b></p>
  <p>在线时间: <b>10 小时</b></p>
  <p>注册时间: <span>2023-04-12</span></p>
  <p>最后登录: <span>2026-06-01</span></p>
</div>
</body></html>
"""

_NOT_LOGGED_IN_HTML = """<!doctype html>
<html><body>
<div class="error">还没有登录，请先登录。</div>
</body></html>
"""

_PARTIAL_PROFILE_HTML = """<!doctype html>
<html><body>
<p>个人资料</p>
<p>用户名: alice</p>
<p>数字ID: 42</p>
</body></html>
"""


# --- mock server ------------------------------------------------------------


@pytest.fixture()
def mock_profile_server() -> Iterator[tuple[str, dict[str, bytes]]]:
    """启动一个本地 HTTP server，根据 path 返回预设 HTML。"""

    state: dict[str, bytes] = {
        "/profile.php": _FULL_PROFILE_HTML.encode("utf-8"),
    }

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            body = state.get(path)
            if body is None:
                self.send_response(int(HTTPStatus.NOT_FOUND))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _endpoints() -> SouthPlusEndpoints:
    return SouthPlusEndpoints(
        site_base_url="https://bbs.south-plus.org",
        login_url="https://bbs.south-plus.org/login.php",
        captcha_url="https://bbs.south-plus.org/ck.php",
        verify_url="https://bbs.south-plus.org/index.php",
        cookie_domains=("south-plus.org",),
        user_agent="pytest-southplus",
    )


def _make_client(base_url: str) -> SouthPlusProfileApi:
    client = SouthPlusProfileApi(SouthPlusSession(_endpoints()))
    # 把抓取入口指向 mock server。
    client.profile_url = f"{base_url}/profile.php"
    client.referer = f"{base_url}/"
    return client


# --- 测试 -------------------------------------------------------------------


def test_fetch_parses_full_profile(
    mock_profile_server: tuple[str, dict[str, bytes]],
) -> None:
    base_url, _ = mock_profile_server
    client = _make_client(base_url)
    profile = client.fetch(cookie_header="eb9e6_winduser=flanchan; eb9e6_winduid=1")
    assert isinstance(profile, UserProfile)
    assert profile.username == "flanchan"
    assert profile.uid == "2030219"
    assert profile.title == "Lv.0"
    assert profile.essence == 3
    assert profile.posts == 128
    assert profile.hp == 50
    assert profile.soul == 20
    assert profile.sp_coin == "14 G"
    assert profile.lp == 7
    assert profile.online_hours == "10 小时"
    assert profile.register_date == "2023-04-12"
    assert profile.last_login_date == "2026-06-01"
    assert profile.avatar_url.endswith("/uploadface/avatar/2030219.jpg")


def test_fetch_raises_on_not_logged_in(
    mock_profile_server: tuple[str, dict[str, bytes]],
) -> None:
    base_url, state = mock_profile_server
    state["/profile.php"] = _NOT_LOGGED_IN_HTML.encode("utf-8")
    client = _make_client(base_url)
    with pytest.raises(SouthPlusProfileError) as exc:
        client.fetch(cookie_header="invalid=cookie")
    assert "Cookie 已失效" in str(exc.value)


def test_fetch_empty_cookie_raises() -> None:
    client = SouthPlusProfileApi(SouthPlusSession(_endpoints()))
    with pytest.raises(SouthPlusProfileError):
        client.fetch(cookie_header="")


def test_parse_falls_back_to_defaults_when_fields_missing() -> None:
    profile = parse_profile_html(_PARTIAL_PROFILE_HTML)
    assert profile.username == "alice"
    assert profile.uid == "42"
    # 缺失字段保留 dataclass 默认。
    assert profile.essence == 0
    assert profile.posts == 0
    assert profile.hp == 0
    assert profile.soul == 0
    assert profile.lp == 0
    assert profile.sp_coin == ""
    assert profile.online_hours == ""
    assert profile.register_date == ""
    assert profile.last_login_date == ""
    # 没有任何头像 URL 命中 -> 回落到站点 logo 占位。
    assert profile.avatar_url.startswith("http")


def test_parse_raises_when_no_logged_in_marker() -> None:
    body = "<html><body>什么都没有</body></html>"
    with pytest.raises(SouthPlusProfileError):
        parse_profile_html(body)


def test_parse_handles_html_entities() -> None:
    body = (
        "<html><body><p>个人资料</p>"
        "<p>用户名: bob</p>"
        "<p>数字ID: <span>99</span></p>"
        "<p>个性签名: hello&nbsp;world</p>"
        "</body></html>"
    )
    profile = parse_profile_html(body)
    assert profile.username == "bob"
    assert "hello" in profile.signature


# --- 头像 .pic > img 选择器与 absolutize -----------------------------------


def test_parse_avatar_uses_pic_class_selector() -> None:
    """phpwind profile.php 的真实头像锚点：``class="pic"`` + 内部 <img>。"""

    body = (
        "<html><body><p>个人资料</p><p>数字ID: 42</p>"
        '<div class="pic"><a href="modify.php"><img src="attachment/photo/2030219.jpg" alt="头像"></a></div>'
        "</body></html>"
    )
    profile = parse_profile_html(body)
    # 相对 URL 已被 absolutize。
    assert (
        profile.avatar_url == "https://bbs.south-plus.org/attachment/photo/2030219.jpg"
    )


def test_parse_avatar_pic_class_supports_td() -> None:
    """phpwind 模板里 ``.pic`` 也可能是 ``<td class="pic">``。"""

    body = (
        "<html><body><p>个人资料</p><p>数字ID: 42</p>"
        '<td class="pic"><img src="//cdn.example.com/face.png"></td>'
        "</body></html>"
    )
    profile = parse_profile_html(body)
    # 协议相对（//cdn...）被补成 https。
    assert profile.avatar_url == "https://cdn.example.com/face.png"


def test_parse_avatar_absolute_url_is_kept() -> None:
    body = (
        "<html><body><p>个人资料</p><p>数字ID: 42</p>"
        '<div class="pic"><img src="https://other.com/foo.jpg"></div>'
        "</body></html>"
    )
    profile = parse_profile_html(body)
    assert profile.avatar_url == "https://other.com/foo.jpg"


def test_parse_avatar_falls_back_to_logo_when_missing() -> None:
    body = "<html><body><p>个人资料</p><p>数字ID: 42</p></body></html>"
    profile = parse_profile_html(body)
    # 没头像 -> 用站点 logo 占位。
    assert profile.avatar_url.startswith("https://bbs.south-plus.org/")
    assert "logo" in profile.avatar_url


# --- username 用 UID 邻接锚定 -----------------------------------------------


def test_parse_username_anchors_on_uid_when_inline_layout() -> None:
    """模拟用户截图里的 ``flanchan (数字ID:2030219) 编辑资料`` 排版。"""

    body = (
        "<html><body><p>个人资料</p>"
        "<h2><a>flanchan</a> <span>(数字ID:2030219)</span> <a>编辑资料</a></h2>"
        '<div class="pic"><img src="/u/2030219.jpg"></div>'
        "</body></html>"
    )
    profile = parse_profile_html(body)
    assert profile.uid == "2030219"
    assert profile.username == "flanchan"


def test_parse_username_falls_back_to_label_form_when_no_inline_layout() -> None:
    body = (
        "<html><body><p>个人资料</p>"
        "<p>用户名: <b>carol</b></p>"
        "<p>数字ID: 999</p>"
        "</body></html>"
    )
    profile = parse_profile_html(body)
    assert profile.uid == "999"
    assert profile.username == "carol"
