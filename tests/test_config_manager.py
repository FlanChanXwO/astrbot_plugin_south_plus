from __future__ import annotations

from pathlib import Path

from src.core.config_manager import PluginConfigManager


def _manager(
    config: dict[str, object] | None = None, *, tmp_path: Path
) -> PluginConfigManager:
    plugin_root = Path(__file__).resolve().parents[1]
    manager = PluginConfigManager(config or {}, plugin_root=plugin_root)
    manager.plugin_data_dir = lambda: tmp_path / "plugin_data"  # type: ignore[assignment]
    return manager


def test_endpoints_are_hardcoded_from_api_constants(tmp_path: Path) -> None:
    manager = _manager(tmp_path=tmp_path)
    endpoints = manager.snapshot().endpoints
    assert endpoints.site_base_url == "https://www.south-plus.net"
    assert endpoints.login_url == "https://www.south-plus.net/login.php"
    assert endpoints.captcha_url == "https://www.south-plus.net/ck.php"
    assert endpoints.verify_url == "https://www.south-plus.net/index.php"
    assert endpoints.cookie_domains == ("www.south-plus.net", "south-plus.net")


def test_user_agent_default_falls_back_to_api_constants(tmp_path: Path) -> None:
    from src.southplus.api import build_endpoints

    manager = _manager(tmp_path=tmp_path)
    # build_endpoints() with no user_agent argument should equal config manager's default.
    assert manager.snapshot().endpoints.user_agent == build_endpoints().user_agent
    assert manager.snapshot().endpoints.user_agent  # non-empty


def test_user_agent_can_be_overridden(tmp_path: Path) -> None:
    manager = _manager({"network": {"user_agent": "custom-ua/1.0"}}, tmp_path=tmp_path)
    assert manager.snapshot().endpoints.user_agent == "custom-ua/1.0"


def test_auth_server_defaults(tmp_path: Path) -> None:
    manager = _manager(tmp_path=tmp_path)
    auth = manager.snapshot().auth_server
    assert auth.token_ttl_seconds == 600
    assert auth.listen_host == "127.0.0.1"
    assert auth.listen_port == 0
    assert auth.base_url == ""


def test_checkin_time_conversion(tmp_path: Path) -> None:
    """验证 HH:mm 被正确转换为 cron 表达式。"""
    manager = _manager(
        {"auto_checkin": {"auto_checkin_time": "09:30"}}, tmp_path=tmp_path
    )
    assert manager.snapshot().auto_checkin_cron == "30 9 * * *"
