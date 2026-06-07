from __future__ import annotations

import datetime
from dataclasses import replace

import pytest

from src.core.datamodels import AddAccountResult, AddAccountStatus, UserRow
from src.southplus.api import CheckinStatus, CheckinTaskResult, UserProfile
from src.utils import (
    decrypt_secret,
    derive_cookie_domains_from_url,
    encrypt_secret,
    format_add_account_result,
    format_checkin_response,
    generate_token,
    get_event_platform,
    is_aiocqhttp_event,
    join_url,
    mask_secret,
    parse_cookie_domains,
    season_name,
)


class _Event:
    def __init__(self, platform: str | None) -> None:
        self._platform = platform

    def get_platform_name(self) -> str | None:
        return self._platform


def test_encrypt_roundtrip() -> None:
    key = "this-is-a-test-key-32-bytes-long-ok"
    plaintext = "eb9e6_winduser=alice; eb9e6_winduid=1"
    cipher = encrypt_secret(plaintext, key)
    assert cipher != plaintext
    assert decrypt_secret(cipher, key) == plaintext


def test_encrypt_with_empty_key_is_passthrough() -> None:
    assert encrypt_secret("foo", "") == "foo"
    assert decrypt_secret("foo", "") == "foo"


def test_decrypt_with_wrong_key_raises() -> None:
    cipher = encrypt_secret("hello", "key-a")
    with pytest.raises(ValueError):
        decrypt_secret(cipher, "key-b-different")


def test_decrypt_plaintext_when_no_prefix() -> None:
    # 兼容历史明文 cookie：当字符串不是 v1: 前缀的密文时直接返回。
    assert decrypt_secret("plain-cookie-value", "secret-key") == "plain-cookie-value"


def test_join_url_normalizes_slashes() -> None:
    assert join_url("https://x.com/", "/login.php") == "https://x.com/login.php"
    assert join_url("https://x.com", "login.php") == "https://x.com/login.php"
    assert join_url("https://x.com//", "//login.php") == "https://x.com/login.php"
    assert join_url("https://x.com/sub", "page") == "https://x.com/sub/page"
    assert join_url("", "/login.php") == "login.php"


def test_parse_cookie_domains_dedupes() -> None:
    assert parse_cookie_domains("a.com, b.com\nA.COM") == ("a.com", "b.com")
    assert parse_cookie_domains("") == ()


def test_derive_cookie_domains_from_url_includes_registrable() -> None:
    assert derive_cookie_domains_from_url("https://www.south-plus.net/login.php") == (
        "www.south-plus.net",
        "south-plus.net",
    )
    assert derive_cookie_domains_from_url("https://bbs.south-plus.org/") == (
        "bbs.south-plus.org",
        "south-plus.org",
    )


def test_mask_secret_keeps_head_and_tail() -> None:
    assert mask_secret("abcdef1234567890") == "abcdef...567890"
    assert mask_secret("short") == "***"
    assert mask_secret("") == ""


def test_generate_token_uses_short_url_safe_code() -> None:
    tokens = {generate_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) == 6 for t in tokens)
    assert all(t.isalnum() for t in tokens)


def test_get_event_platform_normalizes_blank_values() -> None:
    assert get_event_platform(_Event(" aiocqhttp ")) == "aiocqhttp"
    assert get_event_platform(_Event(None)) == ""


def test_is_aiocqhttp_event_detects_onebot_platform() -> None:
    assert is_aiocqhttp_event(_Event("aiocqhttp"))
    assert is_aiocqhttp_event(_Event("napcat-aiocqhttp"))
    assert not is_aiocqhttp_event(_Event("telegram"))


def test_format_add_account_result_created_with_hint() -> None:
    result = _add_result(AddAccountStatus.CREATED)
    text = format_add_account_result(
        result,
        UserProfile(username="alice", uid="10001"),
        auto_checkin_hint=True,
    )
    assert "登录成功：用户名：alice，id：10001" in text
    assert "/spautocheckin 切换当前账号签到" in text


def test_format_add_account_result_refreshed_and_owned_by_other() -> None:
    refreshed = format_add_account_result(
        _add_result(AddAccountStatus.REFRESHED),
        UserProfile(username="", uid=""),
    )
    assert "已刷新 Cookie" in refreshed
    assert "(未记录)" in refreshed
    assert "uid-1" in refreshed

    owned = format_add_account_result(
        _add_result(AddAccountStatus.OWNED_BY_OTHER),
        UserProfile(username="alice", uid="10001"),
    )
    assert "已被其他用户绑定" in owned
    assert "10001" in owned


def test_format_checkin_response_covers_success_done_and_failed() -> None:
    text = format_checkin_response(
        uid="10001",
        today="2026-06-06",
        this_week_label="2026-W23",
        fresh_daily=None,
        fresh_weekly=CheckinTaskResult(
            status=CheckinStatus.SUCCESS,
            message="OK",
        ),
    )
    assert text.split("\n") == [
        "South Plus 主动签到",
        "南+账号：1 个",
        "UID：10001",
        "完成 1：✅ 成功 1",
        "社区·日签：⏭️ 请勿重复签到",
        "社区·周签：✅ 成功",
    ]
    assert "缓存" not in text
    assert "已缓存" not in text

    text = format_checkin_response(
        uid="10001",
        today="2026-06-06",
        this_week_label="2026-W23",
        fresh_daily=CheckinTaskResult(
            status=CheckinStatus.ALREADY_DONE,
            message="already",
        ),
        fresh_weekly=CheckinTaskResult(
            status=CheckinStatus.FAILED,
            message="",
            error="boom",
        ),
    )
    assert "完成 0：✅ 成功 0" in text
    assert "社区·日签：⏭️ 请勿重复签到" in text
    assert "社区·周签：❌ 失败，boom" in text

    text = format_checkin_response(
        uid="10001",
        today="2026-06-06",
        this_week_label="2026-W23",
        fresh_daily=None,
        fresh_weekly=None,
    )
    assert "完成 1：✅ 成功 1" in text
    assert text.count("⏭️ 请勿重复签到") == 2


def test_season_name_boundaries() -> None:
    assert season_name(datetime.datetime(2026, 1, 1)) == "winter"
    assert season_name(datetime.datetime(2026, 3, 1)) == "spring"
    assert season_name(datetime.datetime(2026, 6, 1)) == "summer"
    assert season_name(datetime.datetime(2026, 9, 1)) == "fall"


def _add_result(status: AddAccountStatus) -> AddAccountResult:
    return AddAccountResult(
        status=status,
        account=replace(_user_row(), sp_uid="uid-1"),
    )


def _user_row() -> UserRow:
    return UserRow(
        sp_uid="uid-1",
        account="account-1",
        platform="aiocqhttp",
        cookie="cookie",
        is_active=True,
        created_at="2026-06-06T00:00:00",
        updated_at="2026-06-06T00:00:00",
    )
