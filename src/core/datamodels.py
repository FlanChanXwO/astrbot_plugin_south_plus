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
    platform: str
    expires_at: float


class AddAccountStatus(str, Enum):
    """``UserStore.add_or_update`` 的结果分类。"""

    CREATED = "created"
    REFRESHED = "refreshed"
    OWNED_BY_OTHER = "owned_by_other"


@dataclass(slots=True)
class AddAccountResult:
    """``UserStore.add_or_update`` 的返回值。"""

    status: AddAccountStatus
    account: UserRow


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
    http_proxy: str
    auto_checkin_enabled: bool
    auto_checkin_cron: str
    auto_checkin_concurrency: int
    plugin_data_dir: Path
    database_path: Path
    login_link_strategy: str = "qrcode"
    use_docs_link_wrapper: bool = False
    use_forward_node: bool = False


# ---------------------------------------------------------------------------
# Row 数据类
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserRow:
    """``user`` 表的一行。"""

    sp_uid: str
    account: str
    platform: str
    cookie: str
    is_active: bool
    created_at: str
    updated_at: str
    auto_checkin: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sp_uid": self.sp_uid,
            "account": self.account,
            "platform": self.platform,
            "cookie_masked": mask_secret(self.cookie),
            "is_active": self.is_active,
            "auto_checkin": self.auto_checkin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class GroupRow:
    """``group`` 表的一行。"""

    id: int
    bot_id: str
    platform: str
    group_id: str
    group_name: str
    last_seen_at: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class UserGroupRow:
    """``user_group`` 表的一行。"""

    id: int
    sp_uid: str
    group_id: int
    last_seen_at: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class CheckinRow:
    """``checkin_record`` 表的一行（新：按 task_key 分区 + 全量历史）。"""

    id: int
    sp_uid: str
    task_key: str
    period_key: str
    status: str
    message: str
    error: str
    created_at: str


@dataclass(slots=True)
class ScheduleRow:
    """``schedule`` 表的一行。"""

    id: int
    umo: str
    task_key: str
    cron: str
    params_json: str
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class CheckinSessionExclusionRow:
    """``checkin_session_exclusion`` 表的一行。"""

    id: int
    umo: str
    sp_uid: str
    created_at: str
    updated_at: str
