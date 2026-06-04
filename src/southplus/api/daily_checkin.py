"""South Plus 日签（cid=15）。"""

from __future__ import annotations

from ..client import SouthPlusSession
from ..exceptions import SouthPlusCheckinError
from .constants import DAILY_CID
from ..models import CheckinTaskResult

__all__ = ["SouthPlusDailyCheckinApi"]


class SouthPlusDailyCheckinApi:
    """日签门面：对 cid=15 跑 apply -> collect 流程。

    实际签到逻辑委托给 ``checkin_service``。
    """

    def __init__(
        self,
        session: SouthPlusSession,
        *,
        base_url: str | None = None,
        referer: str | None = None,
    ) -> None:
        self.session = session
        self._base_url = base_url
        self._referer = referer

    def checkin(self, cookie_header: str) -> CheckinTaskResult:
        """跑一次日签。已签/失败均由 ``checkin_service.run`` 包装为 ``CheckinTaskResult``。"""
        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        # 延迟导入避免循环依赖。
        from ..checkin_service import run_checkin

        kwargs: dict = dict(cid=DAILY_CID, label="日签")
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._referer:
            kwargs["referer"] = self._referer
        return run_checkin(self.session, cookie_header, **kwargs)
