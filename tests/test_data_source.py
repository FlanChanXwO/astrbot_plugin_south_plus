from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.db.user_store import UserStore
from src.core.datamodels import AddAccountStatus, UserRow
from src.utils import mask_secret


def _add(store: UserStore, **overrides: str):
    kwargs = {
        "sp_uid": "100",
        "account": "chat:u1",
        "platform": "test",
        "cookie": "ck-alice",
    }
    kwargs.update(overrides)
    return store.add_or_update(**kwargs)  # type: ignore[arg-type]


def test_add_new_account_becomes_active(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    result = _add(store)
    assert result.status is AddAccountStatus.CREATED
    assert isinstance(result.account, UserRow)
    assert result.account.is_active is True
    assert store.get_active("chat:u1", "test").sp_uid == "100"


def test_second_account_steals_active(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    second = _add(store, sp_uid="200")
    assert second.status is AddAccountStatus.CREATED
    assert second.account.is_active is True
    first = store.get_by_uid("100")
    assert first is not None and first.is_active is False
    assert store.get_active("chat:u1", "test").sp_uid == "200"


def test_refresh_existing_account_same_user(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200")
    refreshed = _add(store, sp_uid="100", cookie="ck-renewed")
    assert refreshed.status is AddAccountStatus.REFRESHED
    active = store.get_active("chat:u1", "test")
    assert active.sp_uid == "100"
    assert active.cookie == "ck-renewed"


def test_other_user_cannot_steal_uid(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100", account="chat:u1")
    result = _add(store, sp_uid="100", account="chat:u2", cookie="ck-bad")
    assert result.status is AddAccountStatus.OWNED_BY_OTHER
    row = store.get_by_uid("100")
    assert row.account == "chat:u1"
    assert row.cookie == "ck-alice"


def test_switch_active(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200")
    assert store.get_active("chat:u1", "test").sp_uid == "200"
    assert store.switch_active("chat:u1", "test", "100") is True
    assert store.get_active("chat:u1", "test").sp_uid == "100"


def test_switch_rejects_uid_not_owned(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100", account="chat:u1")
    _add(store, sp_uid="200", account="chat:u2")
    assert store.switch_active("chat:u1", "test", "200") is False
    assert store.get_active("chat:u1", "test").sp_uid == "100"


def test_delete_removes_account_and_falls_back_active(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200")
    assert store.delete_account("chat:u1", "200") is True
    assert store.get_by_uid("200") is None
    assert store.get_active("chat:u1", "test").sp_uid == "100"


def test_delete_rejects_uid_not_owned(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100", account="chat:u1")
    _add(store, sp_uid="200", account="chat:u2")
    assert store.delete_account("chat:u1", "200") is False
    assert store.get_by_uid("200") is not None


def test_list_for_account_orders_active_first(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200")
    store.switch_active("chat:u1", "test", "100")
    items = store.list_for_account("chat:u1", "test")
    assert [a.sp_uid for a in items] == ["100", "200"]
    assert items[0].is_active is True
    assert items[1].is_active is False


def test_cookie_is_encrypted_on_disk(tmp_path: Path) -> None:
    db = tmp_path / "sp.db"
    store = UserStore(db, cookie_encryption_key="key-a")
    _add(store, sp_uid="100", cookie="eb9e6_winduser=alice")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT cookie FROM \"user\" WHERE sp_uid='100'").fetchone()
    assert row is not None
    assert "winduser=alice" not in row[0]
    assert store.get_by_uid("100").cookie == "eb9e6_winduser=alice"


def test_wrong_encryption_key_returns_empty_cookie(tmp_path: Path) -> None:
    db = tmp_path / "sp.db"
    a = UserStore(db, cookie_encryption_key="key-a")
    _add(a, sp_uid="100", cookie="ck-secret")
    b = UserStore(db, cookie_encryption_key="key-b")
    assert b.get_by_uid("100").cookie == ""


def test_list_all(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200", account="chat:u2")
    assert len(store.list_all()) == 2


def test_delete_stale(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    _add(store, sp_uid="200")
    _add(store, sp_uid="300")
    assert store.delete_stale({"100", "200"}) == 1
    assert store.get_by_uid("300") is None
    assert store.get_by_uid("100") is not None


def test_delete_stale_empty_keep_clears_all(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "sp.db")
    _add(store, sp_uid="100")
    assert store.delete_stale(set()) == 1
    assert store.list_all() == []


def test_mask_short_secret() -> None:
    assert mask_secret("short") == "***"
