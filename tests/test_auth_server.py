from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from src.api.client import SouthPlusClient
from src.api.models import LoginRequest, LoginResult, SouthPlusEndpoints
from src.core.auth_server import CredentialFormServer
from src.core.datamodels import AuthServerConfig, CredentialSession
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
    client = SouthPlusClient(endpoints)
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
        with urllib.request.urlopen(server.build_url(session.token)) as response:
            assert response.status == 200
            html = response.read().decode("utf-8")
        assert session.token in html
        assert "/captcha/" in html
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
