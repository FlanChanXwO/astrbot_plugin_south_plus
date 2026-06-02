from __future__ import annotations

import pytest

from src.utils import (
    decrypt_secret,
    derive_cookie_domains_from_url,
    encrypt_secret,
    generate_token,
    join_url,
    mask_secret,
    parse_cookie_domains,
)


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


def test_generate_token_has_high_entropy() -> None:
    tokens = {generate_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 40 for t in tokens)
