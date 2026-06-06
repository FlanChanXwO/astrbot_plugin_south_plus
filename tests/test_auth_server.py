from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import datetime

from src.southplus.api import (
    LoginRequest,
    LoginResult,
    SouthPlusLoginApi,
    SouthPlusEndpoints,
    SouthPlusSession,
)
from src.core.datamodels import AuthServerConfig, CredentialSession
from src.utils import season_name
from src.web.auth_server import CredentialFormServer, _seasonal_logo
from tests.conftest import MockSouthPlusState


def _make_server(
    mock_southplus: MockSouthPlusState,
    *,
    on_success=None,
    ttl: int = 600,
) -> CredentialFormServer:
    endpoints = SouthPlusEndpoints(
        site_base_url=mock_southplus.base_url,
        login_url=f"{mock_southplus.base_url}/login.php",
        captcha_url=f"{mock_southplus.base_url}/ck.php",
        verify_url=f"{mock_southplus.base_url}/index.php",
        cookie_domains=("127.0.0.1",),
        user_agent="pytest-southplus",
    )
    client = SouthPlusLoginApi(SouthPlusSession(endpoints))
    server = CredentialFormServer(
        config=AuthServerConfig(
            listen_host="127.0.0.1",
            listen_port=0,
            base_url="",
            token_ttl_seconds=ttl,
        ),
        client=client,
        on_login_success=on_success or (lambda *_args, **_kwargs: None),
    )
    return server


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    return status, json.loads(body.decode("utf-8"))


def _post_empty(url: str) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_form_page_lists_token_and_captcha(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        assert len(session.token) == 6
        with urllib.request.urlopen(server.build_url(session.token)) as response:
            assert response.status == 200
            html = response.read().decode("utf-8")
        assert session.token in html
        assert "/captcha/" in html
        # 验证季节 logo 出现在渲染的 HTML 中
        expected_logo = _seasonal_logo()
        assert f'src="/assets/{expected_logo}"' in html
        # 验证 body 上有季节 class
        expected_season = season_name()
        assert f'class="season-{expected_season}"' in html
    finally:
        server.shutdown()


def test_captcha_endpoint_returns_png(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        captcha_url = f"http://{server.config.listen_host}:{server.actual_port}/captcha/{session.token}"
        with urllib.request.urlopen(captcha_url) as response:
            assert response.status == 200
            assert response.headers.get("Content-Type", "").startswith(
                "application/octet-stream"
            ) or response.headers.get("Content-Type", "").startswith("image/")
            assert response.read().startswith(b"\x89PNG")
    finally:
        server.shutdown()


def test_full_login_success_invokes_callback(
    mock_southplus: MockSouthPlusState,
) -> None:
    captured: list[tuple[CredentialSession, LoginRequest, LoginResult]] = []

    def on_success(
        session: CredentialSession, request: LoginRequest, result: LoginResult
    ) -> None:
        captured.append((session, request, result))

    server = _make_server(mock_southplus, on_success=on_success)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        captcha_url = f"http://{server.config.listen_host}:{server.actual_port}/captcha/{session.token}"
        with urllib.request.urlopen(captcha_url) as response:
            assert response.status == 200
        submit_url = server.build_url(session.token)
        status, payload = _post_json(
            submit_url,
            {"username": "alice", "password": "secret123", "captcha": "1234"},
        )
        assert status == 200
        assert payload["ok"] is True
        # Captcha 已用，会话清除：再次提交返回过期。
        status2, payload2 = _post_json(
            submit_url,
            {"username": "alice", "password": "secret123", "captcha": "1234"},
        )
        assert status2 == 410 or payload2["ok"] is False
    finally:
        server.shutdown()
    assert len(captured) == 1
    _, request, result = captured[0]
    assert request.username == "alice"
    assert "eb9e6_winduser=alice" in result.cookie


def test_bad_captcha_keeps_session_alive(mock_southplus: MockSouthPlusState) -> None:
    captured: list[LoginResult] = []
    server = _make_server(
        mock_southplus,
        on_success=lambda _session, _request, result: captured.append(result),
    )
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        captcha_url = f"http://{server.config.listen_host}:{server.actual_port}/captcha/{session.token}"
        with urllib.request.urlopen(captcha_url) as response:
            response.read()
        submit_url = server.build_url(session.token)
        status, payload = _post_json(
            submit_url,
            {"username": "alice", "password": "secret123", "captcha": "wrong"},
        )
        assert status == 400
        assert payload["ok"] is False
        # 第二次重试可成功，证明会话未被消费。
        status2, payload2 = _post_json(
            submit_url,
            {"username": "alice", "password": "secret123", "captcha": "1234"},
        )
        assert status2 == 200
        assert payload2["ok"] is True
    finally:
        server.shutdown()
    assert captured and "eb9e6_winduser=alice" in captured[0].cookie


def test_empty_fields_return_400(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        submit_url = server.build_url(session.token)
        status, payload = _post_json(
            submit_url, {"username": "", "password": "", "captcha": ""}
        )
        assert status == 400
        assert payload["ok"] is False
    finally:
        server.shutdown()


def test_invalid_token_returns_410(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        server.ensure_started()
        url = f"http://{server.config.listen_host}:{server.actual_port}/login/bogus"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(url)
        assert exc.value.code == 410
    finally:
        server.shutdown()


def test_cancel_endpoint_removes_session(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        cancel_url = f"http://{server.config.listen_host}:{server.actual_port}/cancel/{session.token}"
        status, payload = _post_empty(cancel_url)
        assert status == 200
        assert payload["ok"] is True
        # 取消后再访问 login 页应返回 410。
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(server.build_url(session.token))
        assert exc.value.code == 410
    finally:
        server.shutdown()


def test_expired_session_auto_evicted(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus, ttl=1)
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        time.sleep(1.2)
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(server.build_url(session.token))
        assert exc.value.code == 410
    finally:
        server.shutdown()


def test_concurrent_submits_do_not_double_login(
    mock_southplus: MockSouthPlusState,
) -> None:
    """同一 token 并发两次提交时，只允许一次抵达 SouthPlus。"""
    successes: list[LoginResult] = []
    server = _make_server(
        mock_southplus,
        on_success=lambda _s, _r, result: successes.append(result),
    )
    try:
        session = server.create_session(user_key="u1", unified_msg_origin="umo")
        captcha_url = f"http://{server.config.listen_host}:{server.actual_port}/captcha/{session.token}"
        with urllib.request.urlopen(captcha_url) as r:
            r.read()
        submit_url = server.build_url(session.token)
        results: list[tuple[int, dict[str, object]]] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                payload = _post_json(
                    submit_url,
                    {"username": "alice", "password": "secret123", "captcha": "1234"},
                )
            except Exception as exc:  # noqa: BLE001
                payload = (-1, {"ok": False, "message": str(exc)})
            with lock:
                results.append(payload)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ok_count = sum(
            1 for status, payload in results if status == 200 and payload.get("ok")
        )
        assert ok_count == 1
    finally:
        server.shutdown()
    assert len(successes) == 1


def test_unknown_path_returns_404(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        server.ensure_started()
        url = f"http://{server.config.listen_host}:{server.actual_port}/garbage"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(url)
        assert exc.value.code == 404
        body = exc.value.read().decode("utf-8")
        assert "页面不存在" in body
    finally:
        server.shutdown()


def test_assets_logo_png_not_served_without_asset_file(
    mock_southplus: MockSouthPlusState,
) -> None:
    server = _make_server(mock_southplus)
    try:
        server.ensure_started()
        url = f"http://{server.config.listen_host}:{server.actual_port}/assets/logo.png"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(url)
        assert exc.value.code == 404
    finally:
        server.shutdown()


def test_assets_path_traversal_rejected(mock_southplus: MockSouthPlusState) -> None:
    server = _make_server(mock_southplus)
    try:
        server.ensure_started()
        # 形式 1: 编码过的斜杠 ..%2F..%2Fmain.py（路由仍把它当一个 segment）。
        url1 = f"http://{server.config.listen_host}:{server.actual_port}/assets/..%2F..%2Fmain.py"
        with pytest.raises(urllib.error.HTTPError) as exc1:
            urllib.request.urlopen(url1)
        assert exc1.value.code == 404
        body1 = exc1.value.read().decode("utf-8")
        assert "from __future__" not in body1

        # 形式 2: 字面的 ../main.py（路由会拆成三段，落到默认 404）。
        url2 = (
            f"http://{server.config.listen_host}:{server.actual_port}/assets/../main.py"
        )
        with pytest.raises(urllib.error.HTTPError) as exc2:
            urllib.request.urlopen(url2)
        assert exc2.value.code == 404
        body2 = exc2.value.read().decode("utf-8")
        assert "from __future__" not in body2
    finally:
        server.shutdown()


def test_season_name_matches_logo() -> None:
    """``season_name`` 与 ``_seasonal_logo`` 的月份判定一致。"""
    for month in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        dt = datetime.datetime(2025, month, 15)
        logo = _seasonal_logo(dt)
        name = season_name(dt)
        assert name in logo, f"{month=}: {name=} not in {logo=}"


def test_seasonal_logo_boundaries() -> None:
    """季节 logo 月份边界测试。"""
    # 冬季：12-2 月
    assert _seasonal_logo(datetime.datetime(2025, 1, 15)) == "logo-winter5.png"
    # 春季：3-5 月
    assert _seasonal_logo(datetime.datetime(2025, 4, 15)) == "logo-spring-south.png"
    # 夏季：6-8 月
    assert _seasonal_logo(datetime.datetime(2025, 7, 15)) == "logo-s-summer2.png"
    # 秋季：9-11 月
    assert _seasonal_logo(datetime.datetime(2025, 10, 15)) == "logo-fall4.png"
    # 边界：12 月
    assert _seasonal_logo(datetime.datetime(2025, 12, 15)) == "logo-winter5.png"
    # 边界：2 月最后一天
    assert _seasonal_logo(datetime.datetime(2025, 2, 28)) == "logo-winter5.png"
    # 边界：3 月 1 日进入春季
    assert _seasonal_logo(datetime.datetime(2025, 3, 1)) == "logo-spring-south.png"


def test_seasonal_logo_defaults_to_current_month() -> None:
    """无参调用不崩溃，返回已知值。"""
    result = _seasonal_logo()
    assert result in (
        "logo-winter5.png",
        "logo-spring-south.png",
        "logo-s-summer2.png",
        "logo-fall4.png",
    )


def test_assets_fallback_to_resources(mock_southplus: MockSouthPlusState) -> None:
    """验证 resources/ 下的季节 logo 可通过 /assets/ 路由访问。"""
    server = _make_server(mock_southplus)
    try:
        server.ensure_started()
        url = (
            f"http://{server.config.listen_host}:{server.actual_port}"
            "/assets/logo-spring-south.png"
        )
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert response.headers.get("Content-Type", "") == "image/png"
            body = response.read()
            assert body.startswith(b"\x89PNG")
    finally:
        server.shutdown()
