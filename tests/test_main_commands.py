from __future__ import annotations

import importlib
import sys
import types
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.datamodels import UserRow


def _load_plugin_class():
    """用最小 AstrBot stub 导入 main.py，只验证本插件命令逻辑。"""
    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    module = importlib.import_module(f"{repo_root.name}.main")
    return module.SouthPlusPlugin, module.PermissionType


class _Event:
    unified_msg_origin = "aiocqhttp:group:100"
    message_str = "/spautocheckin"

    def __init__(self) -> None:
        self.results: list[str] = []

    def get_sender_id(self) -> str:
        return "account-1"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def plain_result(self, text: str) -> str:
        self.results.append(text)
        return text


async def _collect(generator) -> list[str]:
    return [item async for item in generator]


def _plugin_instance():
    SouthPlusPlugin, _ = _load_plugin_class()
    plugin = object.__new__(SouthPlusPlugin)
    plugin.config_snapshot = types.SimpleNamespace(auto_checkin_cron="0 8 * * *")
    plugin.scheduler = MagicMock()
    plugin.store = MagicMock()
    return plugin


def _user(auto_checkin: bool) -> UserRow:
    return UserRow(
        sp_uid="uid-1",
        account="account-1",
        platform="aiocqhttp",
        cookie="cookie",
        is_active=True,
        created_at="2026-06-06T00:00:00",
        updated_at="2026-06-06T00:00:00",
        auto_checkin=auto_checkin,
    )


@pytest.mark.asyncio
async def test_spautocheckin_toggles_enabled_account_to_disabled() -> None:
    plugin = _plugin_instance()
    plugin.store.get_active.return_value = _user(auto_checkin=True)
    event = _Event()

    result = await _collect(plugin.sp_set_auto_checkin(event))

    plugin.store.set_auto_checkin.assert_called_once_with("uid-1", False)
    assert result == ["账号 uid-1 的自动签到已关闭。"]


@pytest.mark.asyncio
async def test_spautocheckin_toggles_disabled_account_to_enabled() -> None:
    plugin = _plugin_instance()
    plugin.store.get_active.return_value = _user(auto_checkin=False)
    event = _Event()

    result = await _collect(plugin.sp_set_auto_checkin(event))

    plugin.store.set_auto_checkin.assert_called_once_with("uid-1", True)
    assert result == ["账号 uid-1 的自动签到已开启。"]


@pytest.mark.asyncio
async def test_spautocheckin_ignores_legacy_arguments() -> None:
    plugin = _plugin_instance()
    plugin.store.get_active.return_value = replace(
        _user(auto_checkin=True), sp_uid="uid-2"
    )
    event = _Event()
    event.message_str = "/spautocheckin on"

    result = await _collect(plugin.sp_set_auto_checkin(event))

    plugin.store.set_auto_checkin.assert_called_once_with("uid-2", False)
    assert result == ["账号 uid-2 的自动签到已关闭。"]


@pytest.mark.asyncio
async def test_spcheckinallsub_subscribes_current_session_when_missing() -> None:
    plugin = _plugin_instance()
    plugin.scheduler.is_subscribed.return_value = False
    event = _Event()

    result = await _collect(plugin.sp_checkin_all_sub_toggle(event))

    plugin.scheduler.is_subscribed.assert_called_once_with(
        "aiocqhttp:group:100",
        "sp.checkin.all",
        {"mode": "all"},
    )
    plugin.scheduler.subscribe.assert_called_once_with(
        "aiocqhttp:group:100",
        task_key="sp.checkin.all",
        cron="0 8 * * *",
        params={"mode": "all"},
    )
    plugin.scheduler.unsubscribe.assert_not_called()
    assert result == ["已订阅本会话的全部账号签到结果推送。"]


@pytest.mark.asyncio
async def test_spcheckinallsub_unsubscribes_current_session_when_present() -> None:
    plugin = _plugin_instance()
    plugin.scheduler.is_subscribed.return_value = True
    event = _Event()

    result = await _collect(plugin.sp_checkin_all_sub_toggle(event))

    plugin.scheduler.unsubscribe.assert_called_once_with(
        "aiocqhttp:group:100",
        "sp.checkin.all",
        {"mode": "all"},
    )
    plugin.scheduler.subscribe.assert_not_called()
    assert result == ["已取消本会话的全部账号签到结果推送。"]


def test_spcheckinallsub_registers_admin_command_and_alias() -> None:
    SouthPlusPlugin, PermissionType = _load_plugin_class()
    handler = SouthPlusPlugin.sp_checkin_all_sub_toggle

    assert handler.__southplus_command__ == {
        "name": "spcheckinallsub",
        "alias": {"sp全局签到订阅"},
    }
    assert handler.__southplus_permission__ == PermissionType.ADMIN


def test_reload_runtime_config_applies_current_checkin_time() -> None:
    SouthPlusPlugin, _ = _load_plugin_class()
    plugin = object.__new__(SouthPlusPlugin)
    plugin.config = {
        "auto_checkin": {
            "auto_checkin_time": "03:00",
            "auto_checkin_concurrency": 5,
        },
    }
    plugin.scheduler = MagicMock()

    plugin._reload_runtime_config()

    plugin.scheduler.reload_config.assert_called_once_with(
        cron="0 3 * * *",
        concurrency=5,
    )
