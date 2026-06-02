"""通用数据模型。

仅包含与 South Plus 站点无关的、本插件框架自有的数据结构。South Plus
站点专有的模型放在 ``src/southplus/models.py``，通过
``src/southplus/api/`` 暴露。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
class StoredAccount:
    """聊天用户在 South Plus 上的一条账号绑定。

    一个聊天用户（``user_key``）可以绑定多个南+账号；每个南+ UID 在数据库
    里全局唯一（用 ``uid`` 作主键）。``is_active`` 表示该聊天用户当前选中
    的账号——查询 / 卡片渲染都用激活账号。
    """

    uid: str
    user_key: str
    unified_msg_origin: str
    username: str
    cookie: str
    is_active: bool
    last_status: str
    last_message: str
    last_run_at: str
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "user_key": self.user_key,
            "unified_msg_origin": self.unified_msg_origin,
            "username": self.username,
            "cookie_masked": mask_secret(self.cookie),
            "is_active": self.is_active,
            "last_status": self.last_status,
            "last_message": self.last_message,
            "last_run_at": self.last_run_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AddAccountStatus(str, Enum):
    """``AccountStore.add_or_update`` 的结果分类。"""

    CREATED = "created"  # 新增了一条绑定
    REFRESHED = "refreshed"  # 当前用户已经绑定过同一 UID，仅刷新 cookie / 切回激活
    OWNED_BY_OTHER = "owned_by_other"  # UID 已被别的聊天用户绑定，操作被拒


@dataclass(slots=True)
class AddAccountResult:
    """``AccountStore.add_or_update`` 的返回值。

    * ``status == CREATED`` -> ``account`` 是新插入的行。
    * ``status == REFRESHED`` -> ``account`` 是刚被刷新的行。
    * ``status == OWNED_BY_OTHER`` -> ``account`` 是占用该 UID 的别人的行，
      ``cookie`` 字段不会被读取——调用方只用它来给用户回话。
    """

    status: AddAccountStatus
    account: StoredAccount


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
