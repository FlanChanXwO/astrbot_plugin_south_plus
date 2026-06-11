from __future__ import annotations

import importlib
import sys
import types
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.datamodels import UserRow


def _load_plugin_module():
    """用最小 AstrBot stub 导入 main.py，只验证本插件命令逻辑。"""
    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    return importlib.import_module(f"{repo_root.name}.main")


def _load_plugin_class():
    module = _load_plugin_module()
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


@pytest.mark.parametrize(
    "scope_attr",
    ["_CHECKIN_REPORT_SCOPE_CURRENT", "_CHECKIN_REPORT_SCOPE_ALL"],
)
def test_checkin_report_message_helpers_share_wording(scope_attr: str) -> None:
    module = _load_plugin_module()
    scope = getattr(module, scope_attr)

    assert (
        module._CHECKIN_REPORT_SUBSCRIBE_HINT
        == "本命令不会立即执行签到，后续将按自动签到时间推送结果。"
    )
    assert module._checkin_report_subscribed_message(scope) == (
        f"已订阅本会话的签到汇报（{scope}）。{module._CHECKIN_REPORT_SUBSCRIBE_HINT}"
    )
    assert (
        module._checkin_report_unsubscribed_message(scope)
        == f"已取消本会话的签到汇报订阅（{scope}）。"
    )
    assert (
        module._checkin_report_not_subscribed_message(scope)
        == f"当前会话未订阅签到汇报（{scope}）。"
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
async def test_spsubcheckin_subscribes_current_account_report_only() -> None:
    module = _load_plugin_module()
    plugin = _plugin_instance()
    event = _Event()

    result = await _collect(plugin.sp_sub_checkin(event))

    plugin.scheduler.subscribe.assert_called_once_with(
        "aiocqhttp:group:100",
        task_key="sp.checkin.session",
        cron="0 8 * * *",
        params={"mode": "session", "account": "account-1"},
    )
    plugin.scheduler.unsubscribe.assert_not_called()
    plugin.scheduler.run_all_checkins.assert_not_called()
    assert result == [
        module._checkin_report_subscribed_message(module._CHECKIN_REPORT_SCOPE_CURRENT)
    ]


@pytest.mark.asyncio
async def test_spunsubcheckin_unsubscribes_current_account_when_present() -> None:
    module = _load_plugin_module()
    plugin = _plugin_instance()
    plugin.scheduler.is_subscribed.return_value = True
    event = _Event()

    result = await _collect(plugin.sp_unsub_checkin(event))

    plugin.scheduler.is_subscribed.assert_called_once_with(
        "aiocqhttp:group:100",
        "sp.checkin.session",
        {"mode": "session", "account": "account-1"},
    )
    plugin.scheduler.unsubscribe.assert_called_once_with(
        "aiocqhttp:group:100",
        "sp.checkin.session",
        {"mode": "session", "account": "account-1"},
    )
    plugin.scheduler.subscribe.assert_not_called()
    assert result == [
        module._checkin_report_unsubscribed_message(
            module._CHECKIN_REPORT_SCOPE_CURRENT
        )
    ]


@pytest.mark.asyncio
async def test_spunsubcheckin_reports_current_account_not_subscribed() -> None:
    module = _load_plugin_module()
    plugin = _plugin_instance()
    plugin.scheduler.is_subscribed.return_value = False
    event = _Event()

    result = await _collect(plugin.sp_unsub_checkin(event))

    plugin.scheduler.is_subscribed.assert_called_once_with(
        "aiocqhttp:group:100",
        "sp.checkin.session",
        {"mode": "session", "account": "account-1"},
    )
    plugin.scheduler.unsubscribe.assert_not_called()
    plugin.scheduler.subscribe.assert_not_called()
    assert result == [
        module._checkin_report_not_subscribed_message(
            module._CHECKIN_REPORT_SCOPE_CURRENT
        )
    ]


@pytest.mark.asyncio
async def test_spcheckinallsub_subscribes_current_session_when_missing() -> None:
    module = _load_plugin_module()
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
    assert result == [
        module._checkin_report_subscribed_message(module._CHECKIN_REPORT_SCOPE_ALL)
    ]


@pytest.mark.asyncio
async def test_spcheckinallsub_unsubscribes_current_session_when_present() -> None:
    module = _load_plugin_module()
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
    assert result == [
        module._checkin_report_unsubscribed_message(module._CHECKIN_REPORT_SCOPE_ALL)
    ]


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
