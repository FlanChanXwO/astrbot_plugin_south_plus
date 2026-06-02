from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.data_source import AccountStore
from src.core.datamodels import AddAccountStatus, StoredAccount
from src.utils import mask_secret


def _add(store: AccountStore, **overrides: object):
    kwargs = {
        "uid": "100",
        "user_key": "chat:u1",
        "unified_msg_origin": "plat:sess",
        "username": "alice",
        "cookie": "ck-alice",
    }
    kwargs.update(overrides)
    return store.add_or_update(**kwargs)  # type: ignore[arg-type]


def test_add_new_account_becomes_active(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    result = _add(store)
    assert result.status is AddAccountStatus.CREATED
    assert isinstance(result.account, StoredAccount)
    assert result.account.is_active is True
    assert store.get_active("chat:u1").uid == "100"


def test_second_account_steals_active(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100")
    second = _add(store, uid="200", username="bob")
    assert second.status is AddAccountStatus.CREATED
    assert second.account.is_active is True
    # 第一条被自动设为非激活。
    first = store.get_by_uid("100")
    assert first is not None and first.is_active is False
    # 激活账号是 200。
    assert store.get_active("chat:u1").uid == "200"


def test_refresh_existing_account_same_user(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100")
    _add(store, uid="200")
    # 在激活账号是 200 的情况下，重新登录 100，应该 REFRESHED 并切回 100。
    refreshed = _add(store, uid="100", cookie="ck-renewed", username="alice-new")
    assert refreshed.status is AddAccountStatus.REFRESHED
    active = store.get_active("chat:u1")
    assert active.uid == "100"
    assert active.username == "alice-new"
    assert active.cookie == "ck-renewed"


def test_other_user_cannot_steal_uid(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100", user_key="chat:u1")
    result = _add(
        store,
        uid="100",
        user_key="chat:u2",
        unified_msg_origin="plat:other",
        username="malice",
        cookie="ck-bad",
    )
    assert result.status is AddAccountStatus.OWNED_BY_OTHER
    # 数据库里这条 UID 仍属于 u1，cookie 未变。
    row = store.get_by_uid("100")
    assert row.user_key == "chat:u1"
    assert row.cookie == "ck-alice"


def test_switch_active(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100")
    _add(store, uid="200")
    assert store.get_active("chat:u1").uid == "200"
    assert store.switch_active("chat:u1", "100") is True
    assert store.get_active("chat:u1").uid == "100"


def test_switch_rejects_uid_not_owned(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100", user_key="chat:u1")
    _add(store, uid="200", user_key="chat:u2")
    assert store.switch_active("chat:u1", "200") is False
    assert store.get_active("chat:u1").uid == "100"


def test_delete_removes_account_and_falls_back_active(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100")
    _add(store, uid="200")  # 激活为 200
    assert store.delete_account("chat:u1", "200") is True
    # 200 被删除，剩下 100 自动接管激活位。
    assert store.get_by_uid("200") is None
    assert store.get_active("chat:u1").uid == "100"


def test_delete_rejects_uid_not_owned(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100", user_key="chat:u1")
    _add(store, uid="200", user_key="chat:u2")
    assert store.delete_account("chat:u1", "200") is False
    assert store.get_by_uid("200") is not None


def test_list_for_user_orders_active_first(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "sp.db")
    _add(store, uid="100")
    _add(store, uid="200")
    store.switch_active("chat:u1", "100")
    items = store.list_for_user("chat:u1")
    assert [a.uid for a in items] == ["100", "200"]
    assert items[0].is_active is True
    assert items[1].is_active is False


def test_cookie_is_encrypted_on_disk(tmp_path: Path) -> None:
    db = tmp_path / "sp.db"
    store = AccountStore(db, cookie_encryption_key="key-a")
    _add(store, uid="100", cookie="eb9e6_winduser=alice")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT cookie FROM accounts WHERE uid='100'").fetchone()
    assert row is not None
    assert "winduser=alice" not in row[0]
    # 读回来透明解密。
    assert store.get_by_uid("100").cookie == "eb9e6_winduser=alice"


def test_wrong_encryption_key_returns_empty_cookie(tmp_path: Path) -> None:
    db = tmp_path / "sp.db"
    a = AccountStore(db, cookie_encryption_key="key-a")
    _add(a, uid="100", cookie="ck-secret")
    b = AccountStore(db, cookie_encryption_key="key-b")
    assert b.get_by_uid("100").cookie == ""


def test_mask_short_secret() -> None:
    assert mask_secret("short") == "***"
