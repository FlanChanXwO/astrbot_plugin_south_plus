from __future__ import annotations

from pathlib import Path

from src.core.data_source import CredentialStore
from src.core.datamodels import StoredCredential
from src.utils import mask_secret


def test_store_round_trip_plain(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "southplus.db")
    store.upsert_credential(
        user_key="u1",
        unified_msg_origin="platform:session",
        username="alice",
        cookie="abcdef1234567890",
        schedule_time="03:30",
    )

    item = store.get("u1")

    assert item is not None
    assert isinstance(item, StoredCredential)
    assert item.username == "alice"
    assert item.enabled is True
    assert item.schedule_time == "03:30"
    assert item.cookie == "abcdef1234567890"
    assert store.list_all()[0].to_public_dict()["cookie_masked"] == "abcdef...567890"


def test_store_encrypts_cookie_on_disk(tmp_path: Path) -> None:
    key = "encryption-key-for-test"
    store = CredentialStore(tmp_path / "southplus.db", cookie_encryption_key=key)
    cookie = "eb9e6_winduser=alice; eb9e6_windpwd=hash; eb9e6_winduid=1"
    store.upsert_credential(
        user_key="u1",
        unified_msg_origin="platform:session",
        username="alice",
        cookie=cookie,
    )

    import sqlite3

    with sqlite3.connect(tmp_path / "southplus.db") as conn:
        row = conn.execute(
            "SELECT cookie FROM credentials WHERE user_key='u1'"
        ).fetchone()
    assert row is not None
    assert cookie not in row[0]
    assert row[0] != cookie

    # 读取时透明解密。
    fetched = store.get("u1")
    assert fetched is not None
    assert fetched.cookie == cookie


def test_store_with_mismatched_key_returns_empty_cookie(tmp_path: Path) -> None:
    store_a = CredentialStore(tmp_path / "southplus.db", cookie_encryption_key="key-a")
    store_a.upsert_credential(
        user_key="u1",
        unified_msg_origin="origin",
        username="alice",
        cookie="cookie-value",
    )
    store_b = CredentialStore(tmp_path / "southplus.db", cookie_encryption_key="key-b")
    item = store_b.get("u1")
    assert item is not None
    assert item.cookie == ""


def test_mask_short_secret() -> None:
    assert mask_secret("short") == "***"
