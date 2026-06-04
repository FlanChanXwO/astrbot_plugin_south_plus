from __future__ import annotations

import pytest

from src.southplus.api import (
    LoginRequest,
    SouthPlusLoginApi,
    SouthPlusEndpoints,
    SouthPlusLoginError,
    SouthPlusSession,
)
from tests.conftest import MockSouthPlusState


def _endpoints(state: MockSouthPlusState) -> SouthPlusEndpoints:
    return SouthPlusEndpoints(
        site_base_url=state.base_url,
        login_url=f"{state.base_url}/login.php",
        captcha_url=f"{state.base_url}/ck.php",
        verify_url=f"{state.base_url}/index.php",
        cookie_domains=("127.0.0.1",),
        user_agent="pytest-southplus",
    )


def test_fetch_captcha_returns_png(mock_southplus: MockSouthPlusState) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with client.new_attempt() as attempt:
        payload = attempt.fetch_captcha()
    assert payload.body.startswith(b"\x89PNG")
    assert mock_southplus.captcha_calls == 1


def test_submit_success_returns_cookie_header(
    mock_southplus: MockSouthPlusState,
) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with client.new_attempt() as attempt:
        attempt.fetch_captcha()
        result = attempt.submit(
            LoginRequest(username="alice", password="secret123", captcha="1234")
        )
    assert "eb9e6_winduser=alice" in result.cookie
    assert "eb9e6_winduid=1" in result.cookie
    assert mock_southplus.last_login_payload["step"] == "2"
    assert mock_southplus.last_login_payload["hideid"] == "0"
    assert mock_southplus.last_login_payload["cktime"] == "31536000"


def test_submit_bad_captcha_classifies_failure(
    mock_southplus: MockSouthPlusState,
) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with client.new_attempt() as attempt:
        attempt.fetch_captcha()
        with pytest.raises(SouthPlusLoginError) as exc:
            attempt.submit(
                LoginRequest(username="alice", password="secret123", captcha="bad")
            )
    assert "验证码" in str(exc.value) or "认证码" in str(exc.value)


def test_submit_bad_password_classifies_failure(
    mock_southplus: MockSouthPlusState,
) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with client.new_attempt() as attempt:
        attempt.fetch_captcha()
        with pytest.raises(SouthPlusLoginError) as exc:
            attempt.submit(
                LoginRequest(username="alice", password="wrong", captcha="1234")
            )
    assert "账号" in str(exc.value) or "密码" in str(exc.value)


def test_check_cookie_passes_when_logged_in_marker_present(
    mock_southplus: MockSouthPlusState,
) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    cookie = "eb9e6_winduser=alice; eb9e6_winduid=1"
    assert client.check_cookie(cookie) == cookie


def test_check_cookie_rejects_login_page(mock_southplus: MockSouthPlusState) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with pytest.raises(SouthPlusLoginError):
        client.check_cookie("garbage=value")


def test_attempt_reuses_same_cookie_jar_for_captcha_and_submit(
    mock_southplus: MockSouthPlusState,
) -> None:
    client = SouthPlusLoginApi(SouthPlusSession(_endpoints(mock_southplus)))
    with client.new_attempt() as attempt:
        attempt.fetch_captcha()
        attempt.fetch_captcha()
        result = attempt.submit(
            LoginRequest(username="alice", password="secret123", captcha="1234")
        )
    assert mock_southplus.captcha_calls == 2
    assert "eb9e6_winduser=alice" in result.cookie
