"""South Plus 社区签到（日签 + 周签）抓包。

参考：``https://github.com/MeYangGe/SouthPlusQianDao`` 中的 APPLY*/COLLECT*
四个脚本。

抓包要点（``docs/southplus-capture.md`` 中收录）：

* 入口：``{base}/plugin.php`` (GET)，``H_name=tasks`` & ``action=ajax``。
* 流程：每个任务两步——``actions=job`` 申请、``actions=job2`` 领取奖励。
* 任务类别：``cid=15`` 日签、``cid=14`` 周签。
* 时间戳：``nowtime`` 取毫秒整数；参考代码用固定值实际也工作。
* ``verify``：参考仓库观察是固定 ``5af36471``，似乎暂未严格校验；保留为
  常量并加 TODO，必要时改为从 tasks 页面动态抓。
* 响应：XML，``<root>`` 元素的 text 是 tab 分隔字段，第一段是动作码，
  第二段是中文文案（成功时含"完成"/"奖励"/"申请"等关键字）。
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from .models import (
    CheckinReport,
    CheckinStatus,
    CheckinTaskResult,
    SouthPlusEndpoints,
)

# 用户截图与提示中明确给出的签到入口域名。
BBS_BASE_URL = "https://bbs.south-plus.org"
TASKS_REFERER = f"{BBS_BASE_URL}/plugin.php?H_name-tasks-actions-newtasks.html.html"

# 任务 ID。
DAILY_CID = "15"
WEEKLY_CID = "14"

# phpwind 的"申请任务" / "领取奖励"两段动作。
ACTION_APPLY = "job"
ACTION_COLLECT = "job2"

# verify 在 MeYangGe 参考仓库里观察到是固定值。新版本若校验更严，应改为
# 从 tasks 页面 HTML 抓出该 token。
# TODO(southplus-capture): 若 verify 校验生效，改为预先 GET tasks 页面解析。
DEFAULT_VERIFY = "5af36471"

# 站点返回 XML，CDATA 字段以 tab 分隔。成功/失败靠下面这两组关键字判定。
_SUCCESS_KEYWORDS = ("完成", "奖励", "成功", "申请", "领取", "进行中")
# apply 阶段命中这些 = 这周期任务以前签过了，跳过 collect。
_ALREADY_DONE_KEYWORDS = (
    "已完成",
    "已领取",
    "请勿重复",
    "重复",
    "已经",
    "今天已经",
    "本周已经",
)
# collect 阶段："已完成"是字面正常领取，不算重复——只在文案明确指向"重复 /
# 已经签过"时才把 collect 结果回落 ALREADY_DONE。
_REPEAT_KEYWORDS = (
    "请勿重复",
    "重复",
    "已经",
    "今天已经",
    "本周已经",
    "已领取",
)


class SouthPlusCheckinError(RuntimeError):
    """签到流程在客户端层抛出的错误，可向用户展示。"""


@dataclass(slots=True)
class _RawResponse:
    """单次 plugin.php?actions=job/job2 的解析结果。"""

    action: str
    message: str
    extra: str
    raw_body: str


class SouthPlusCheckinClient:
    """签到门面：``checkin(cookie)`` 跑完整日签 + 周签流程。

    每次签到都开一个独立的 ``httpx.Client``，与登录/资料抓取互不共享会话。
    """

    def __init__(
        self,
        endpoints: SouthPlusEndpoints,
        *,
        http_proxy: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.endpoints = endpoints
        self.http_proxy = http_proxy or None
        # 测试可注入 mock 服务器 URL。生产路径上一直是 BBS_BASE_URL。
        self.base_url = (base_url or BBS_BASE_URL).rstrip("/")
        self.referer = TASKS_REFERER

    # --- 对外入口 -----------------------------------------------------------

    def checkin(self, cookie_header: str) -> CheckinReport:
        """跑一次完整签到流程。日 + 周两个任务独立尝试，互不影响。"""

        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        daily = self._safe_run(cookie_header, cid=DAILY_CID, label="日签")
        weekly = self._safe_run(cookie_header, cid=WEEKLY_CID, label="周签")
        return CheckinReport(daily=daily, weekly=weekly)

    def checkin_daily(self, cookie_header: str) -> CheckinTaskResult:
        """单独跑日签（``cid=15``）。已签情况由调用方在 DB 层先过滤。"""

        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        return self._safe_run(cookie_header, cid=DAILY_CID, label="日签")

    def checkin_weekly(self, cookie_header: str) -> CheckinTaskResult:
        """单独跑周签（``cid=14``）。"""

        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        return self._safe_run(cookie_header, cid=WEEKLY_CID, label="周签")

    # --- 单任务（apply -> collect） ----------------------------------------

    def _safe_run(
        self, cookie_header: str, *, cid: str, label: str
    ) -> CheckinTaskResult:
        """跑单个任务（apply -> collect），把异常包成 failed。"""

        try:
            return self._run(cookie_header, cid=cid, label=label)
        except SouthPlusCheckinError as exc:
            return CheckinTaskResult(
                status=CheckinStatus.FAILED,
                message=str(exc),
                error=str(exc),
            )
        except httpx.HTTPError as exc:
            return CheckinTaskResult(
                status=CheckinStatus.FAILED,
                message=f"{label} 网络错误",
                error=f"httpx: {exc!r}",
            )
        except Exception as exc:  # noqa: BLE001
            return CheckinTaskResult(
                status=CheckinStatus.FAILED,
                message=f"{label} 未预期异常",
                error=repr(exc),
            )

    def _run(self, cookie_header: str, *, cid: str, label: str) -> CheckinTaskResult:
        with self._open_client(cookie_header) as client:
            apply_raw = self._request(client, cid=cid, actions=ACTION_APPLY)
            apply_resp = _parse_response(apply_raw)
            # apply 阶段如果显式说"已完成/重复"，把它当成 ALREADY_DONE，无需 collect。
            if _matches_any(apply_resp.message, _ALREADY_DONE_KEYWORDS):
                return CheckinTaskResult(
                    status=CheckinStatus.ALREADY_DONE,
                    message=f"{label}：{apply_resp.message}",
                )
            if not _matches_any(apply_resp.message, _SUCCESS_KEYWORDS):
                return CheckinTaskResult(
                    status=CheckinStatus.FAILED,
                    message=f"{label} 申请阶段失败：{apply_resp.message or '(空响应)'}",
                    error=apply_resp.raw_body,
                )

            collect_raw = self._request(client, cid=cid, actions=ACTION_COLLECT)
            collect_resp = _parse_response(collect_raw)

        # collect 阶段的"已完成"是字面意思（刚刚领取完成了任务）——不要把它
        # 错判成 ALREADY_DONE。只在文案明显表达"重复/已签"语义时才回落
        # ALREADY_DONE。
        if _matches_any(collect_resp.message, _REPEAT_KEYWORDS):
            return CheckinTaskResult(
                status=CheckinStatus.ALREADY_DONE,
                message=f"{label}：{collect_resp.message}",
            )
        if _matches_any(collect_resp.message, _SUCCESS_KEYWORDS):
            extra = f"（{collect_resp.extra}）" if collect_resp.extra else ""
            return CheckinTaskResult(
                status=CheckinStatus.SUCCESS,
                message=f"{label}：{collect_resp.message}{extra}",
            )
        return CheckinTaskResult(
            status=CheckinStatus.FAILED,
            message=f"{label} 领取阶段失败：{collect_resp.message or '(空响应)'}",
            error=collect_resp.raw_body,
        )

    # --- httpx 细节 --------------------------------------------------------

    def _open_client(self, cookie_header: str) -> httpx.Client:
        headers = {
            "User-Agent": self.endpoints.user_agent,
            "Cookie": cookie_header,
            "Referer": self.referer,
            "Accept-Language": "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        }
        return httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=20.0,
            proxy=self.http_proxy,
        )

    def _request(self, client: httpx.Client, *, cid: str, actions: str) -> str:
        params = {
            "H_name": "tasks",
            "action": "ajax",
            "actions": actions,
            "cid": cid,
            "nowtime": str(int(time.time() * 1000)),
            "verify": DEFAULT_VERIFY,
        }
        url = f"{self.base_url}/plugin.php"
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.text


def _parse_response(raw: str) -> _RawResponse:
    """解析 ``<root>action\\tmessage[\\textra]</root>`` 形态的 XML。

    任何解析失败都把整段 raw 留在 message 里，让 ``_run`` 走 FAILED 分支。
    """

    body = raw.strip()
    if not body:
        return _RawResponse(action="", message="", extra="", raw_body=raw)
    try:
        root = ET.fromstring(body)
        text = root.text or ""
    except ET.ParseError:
        return _RawResponse(action="", message=body, extra="", raw_body=raw)
    parts = text.split("\t")
    if len(parts) == 1:
        return _RawResponse(action="", message=parts[0].strip(), extra="", raw_body=raw)
    if len(parts) == 2:
        return _RawResponse(
            action=parts[0].strip(),
            message=parts[1].strip(),
            extra="",
            raw_body=raw,
        )
    return _RawResponse(
        action=parts[0].strip(),
        message=parts[1].strip(),
        extra=parts[2].strip(),
        raw_body=raw,
    )


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
