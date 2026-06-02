"""通用数据模型。

仅包含与 South Plus 站点无关的、本插件框架自有的数据结构。South Plus
站点专有的模型放在 ``src/api/models.py``。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..southplus.api import SouthPlusEndpoints
from ..utils import mask_secret


@dataclass(slots=True)
class CredentialSession:
    token: str
    user_key: str
    unified_msg_origin: str
    expires_at: float


@dataclass(slots=True)
class StoredCredential:
    user_key: str
    unified_msg_origin: str
    username: str
    cookie: str
    enabled: bool
    schedule_time: str
    last_status: str
    last_message: str
    last_run_at: str
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "user_key": self.user_key,
            "unified_msg_origin": self.unified_msg_origin,
            "username": self.username,
            "cookie_masked": mask_secret(self.cookie),
            "enabled": self.enabled,
            "schedule_time": self.schedule_time,
            "last_status": self.last_status,
            "last_message": self.last_message,
            "last_run_at": self.last_run_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class AuthServerConfig:
    listen_host: str
    listen_port: int
    base_url: str
    token_ttl_seconds: int


@dataclass(slots=True)
class PluginConfigSnapshot:
    endpoints: SouthPlusEndpoints
    auth_server: AuthServerConfig
    cookie_encryption_key: str
    http_proxy: str
    plugin_data_dir: Path
    database_path: Path
