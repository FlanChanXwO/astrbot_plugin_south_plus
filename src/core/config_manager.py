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
            http_proxy=self.get_str("network.http_proxy"),
            auto_checkin_enabled=self.get_bool("auto_checkin.auto_checkin_enabled"),
            auto_checkin_cron=self._checkin_time_to_cron(),
            auto_checkin_concurrency=self.get_int(
                "auto_checkin.auto_checkin_concurrency"
            ),
            plugin_data_dir=plugin_data_dir,
            database_path=plugin_data_dir / "southplus.db",
            login_link_strategy=self.get_str("login_link.login_link_strategy"),
            use_docs_link_wrapper=self.get_bool("login_link.use_docs_link_wrapper"),
            use_forward_node=self.get_bool("login_link.use_forward_node"),
        )

    def _checkin_time_to_cron(self) -> str:
        """将 HH:mm 格式的签到时间转换为 cron 表达式（分 时 * * *）。"""
        raw = self.get_str("auto_checkin.auto_checkin_time")
        try:
            hh, mm = raw.split(":")
            hour = int(hh)
            minute = int(mm)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            return f"{minute} {hour} * * *"
        except (ValueError, AttributeError):
            import warnings

            warnings.warn(
                f"auto_checkin_time 格式无效（{raw!r}），已回退到默认 08:00。",
                stacklevel=2,
            )
            return "0 8 * * *"

    def plugin_data_dir(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        plugin_data = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        plugin_data.mkdir(parents=True, exist_ok=True)
        return plugin_data

    def _endpoints(self) -> SouthPlusEndpoints:
        return build_endpoints(user_agent=self.get_str("network.user_agent"))

    def _auth_server(self) -> AuthServerConfig:
        return AuthServerConfig(
            listen_host=self.get_str("auth_server.auth_listen_host"),
            listen_port=self.get_int("auth_server.auth_listen_port"),
            base_url=self.get_str("auth_server.auth_base_url"),
            token_ttl_seconds=self.get_int("auth_server.auth_token_ttl_seconds"),
        )

    # ------------------------------------------------------------------
    # 带点号路径的 get helpers
    # ------------------------------------------------------------------

    def get_str(self, key: str) -> str:
        return str(self._value(key)).strip()

    def get_int(self, key: str) -> int:
        value = self._value(key)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"插件配置 {key} 必须是整数，当前值为 {value!r}") from exc

    def get_bool(self, key: str) -> bool:
        value = self._value(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    # ------------------------------------------------------------------
    # 核心：支持 "group.field" 点号路径
    # ------------------------------------------------------------------

    def _value(self, key: str) -> Any:
        """按 ``group.field`` 路径从运行时配置或 schema 默认值中取值。"""
        parts = key.split(".")

        # 1) 从运行时配置（嵌套 dict）中查找
        node: Any = self._config
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = None
                break
        if node is not None:
            return node

        # 2) fallback 到 schema 默认值
        schema_node: Any = self._schema
        for part in parts:
            if not isinstance(schema_node, dict):
                schema_node = None
                break
            entry = schema_node.get(part)
            if isinstance(entry, dict) and entry.get("type") == "object":
                schema_node = entry.get("items", {})
            else:
                schema_node = entry
        if isinstance(schema_node, dict) and "default" in schema_node:
            return schema_node["default"]

        raise KeyError(f"插件配置 {key} 不存在于 _conf_schema.json")

    # ------------------------------------------------------------------
    # Schema 加载
    # ------------------------------------------------------------------

    def _load_schema(self) -> dict[str, Any]:
        schema_path = self._plugin_root / "_conf_schema.json"
        with schema_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError("_conf_schema.json 顶层必须是对象")
        return data
