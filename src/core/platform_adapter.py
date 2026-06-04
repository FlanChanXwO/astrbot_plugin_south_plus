"""平台成员关系适配器。

``PlatformMembershipAdapter`` ABC 定义了查询 bot 与用户之间关系的接口；
``NapCatMembershipAdapter`` 通过 OneBot11 HTTP API 实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..utils.logger import plugin_logger

if TYPE_CHECKING:
    from astrbot.api.star import Context


class PlatformMembershipAdapter(ABC):
    """查询 bot 平台中用户关系状态的抽象接口。

    返回值语义：
    * ``True`` — 确认用户在群 / 是好友
    * ``False`` — 确认用户不在群 / 不是好友
    * ``None`` — 当前平台不支持此查询，上层应跳过
    """

    @abstractmethod
    async def is_friend(self, account: str, platform: str) -> bool | None: ...

    @abstractmethod
    async def is_in_group(
        self,
        account: str,
        group_id: str,
        platform: str,
    ) -> bool | None: ...


class NapCatMembershipAdapter(PlatformMembershipAdapter):
    """通过 OneBot11 HTTP API 查询 NapCat / aiocqhttp 中的关系。"""

    def __init__(self, context: Context) -> None:
        self._context = context

    async def is_friend(self, account: str, platform: str) -> bool | None:
        client = self._get_client(platform)
        if client is None:
            return None
        try:
            friend_list: list[dict] = await client.call_action("get_friend_list")  # type: ignore[union-attr]
        except Exception as exc:
            plugin_logger.warning(f"get_friend_list 失败 platform={platform}: {exc}")
            return None
        return any(str(f.get("user_id", "")) == str(account) for f in friend_list)

    async def is_in_group(
        self,
        account: str,
        group_id: str,
        platform: str,
    ) -> bool | None:
        client = self._get_client(platform)
        if client is None:
            return None
        try:
            members: list[dict] = await client.call_action(  # type: ignore[union-attr]
                "get_group_member_list",
                group_id=int(group_id),
            )
        except Exception as exc:
            plugin_logger.warning(
                f"get_group_member_list 失败 platform={platform} group={group_id}: {exc}"
            )
            return None
        return any(str(m.get("user_id", "")) == str(account) for m in members)

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------

    def _get_client(self, platform: str):
        """按 platform 名取 CQHttp 客户端。"""
        inst = self._context.get_platform_inst(platform)
        if inst is None:
            plugin_logger.debug(f"未找到 platform 实例：{platform}")
            return None
        return inst.get_client()
