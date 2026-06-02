from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..southplus.api import SouthPlusEndpoints, build_endpoints
from ..shared.constants import PLUGIN_NAME
from .datamodels import AuthServerConfig, PluginConfigSnapshot


class PluginConfigManager:
    def __init__(
        self, config: dict[str, Any] | None = None, *, plugin_root: Path | None = None
    ) -> None:
        self._config = config or {}
        self._plugin_root = plugin_root or Path(__file__).resolve().parents[2]
        self._schema = self._load_schema()

    def snapshot(self) -> PluginConfigSnapshot:
        plugin_data_dir = self.plugin_data_dir()
        return PluginConfigSnapshot(
            endpoints=self._endpoints(),
            auth_server=self._auth_server(),
            cookie_encryption_key=self.get_str("cookie_encryption_key"),
            http_proxy=self.get_str("http_proxy"),
            plugin_data_dir=plugin_data_dir,
            database_path=plugin_data_dir / "southplus.db",
        )

    def plugin_data_dir(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        plugin_data = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        plugin_data.mkdir(parents=True, exist_ok=True)
        return plugin_data

    def _endpoints(self) -> SouthPlusEndpoints:
        # South Plus 站点本身（域名、URL 路径、cookie 域）由抓包结论硬编码在
        # src/api/constants.py 中，不暴露给用户配置。只有 UA 可被用户覆盖，
        # 因为反爬升级时换 UA 是最常见的兜底手段。
        return build_endpoints(user_agent=self.get_str("user_agent"))

    def _auth_server(self) -> AuthServerConfig:
        return AuthServerConfig(
            listen_host=self.get_str("auth_listen_host"),
            listen_port=self.get_int("auth_listen_port"),
            base_url=self.get_str("auth_base_url"),
            token_ttl_seconds=self.get_int("auth_token_ttl_seconds"),
        )

    def get_str(self, key: str) -> str:
        return str(self._value(key)).strip()

    def get_int(self, key: str) -> int:
        value = self._value(key)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"插件配置 {key} 必须是整数，当前值为 {value!r}") from exc

    def _value(self, key: str) -> Any:
        value = self._config.get(key, None)
        if value is not None:
            return value
        if key not in self._schema:
            raise KeyError(f"插件配置 {key} 不存在于 _conf_schema.json")
        return self._schema[key].get("default")

    def _load_schema(self) -> dict[str, Any]:
        schema_path = self._plugin_root / "_conf_schema.json"
        with schema_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError("_conf_schema.json 顶层必须是对象")
        return data
