"""South Plus 签到服务。

包含签到共享逻辑（apply -> collect -> verify 三段流程、XML 解析、状态判定）
以及对外门面 ``CheckinService``（日签 cid=15 + 周签 cid=14）。

签到流程依据 phpwind 任务状态机：

* state A = 未申请；
* state B = 已申请未领取；
* state C = 已领取（完成）。常伴随 18 小时冷却拒绝。

完整一次签到必须把任务从 A 推到 C：

1. ``apply`` (actions=job)：
   * A -> B（"申请[日常]任务完成,请赶紧去完成任务吧!"）；
   * B -> B（"已经申请[日常]完成,请赶紧..."）；
   * C -> C（"请勿重复申请..." / "拒离上次申请[日常]还没超过 N 小时" /
     "本周已完成"）——短路成 ALREADY_DONE，不再走 collect / verify。
2. ``collect`` (actions=job2)：
   * B -> C（"完成[日常]任务,获得奖励\t10 G"）；
   * C -> 报错 "你[日常]已经完成!" / "请勿重复..." / "未申请任务!"——后者
     是 phpwind 把 state-C 任务从"进行中"列表里抽走后的副作用，按用户口径
     统一当作 ALREADY_DONE（"请勿重复签到"）。
3. ``verify``：再调一次 ``apply``，期望响应命中 state-C 关键字。这是站点级别
   的"领取后真的进了完成列表"程序化校验：只有 verify 也确认 state-C 才算
   签到成功。
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from .client import SouthPlusSession
from .exceptions import SouthPlusCheckinError
from .api.constants import (
    ACTION_APPLY,
    ACTION_COLLECT,
    APPLY_ALREADY_COLLECTED_KEYWORDS,
    APPLY_NEEDS_COLLECT_KEYWORDS,
    BBS_BASE_URL,
    COLLECT_ALREADY_DONE_KEYWORDS,
    COLLECT_SUCCESS_KEYWORDS,
    DAILY_CID,
    DEFAULT_CHECKIN_VERIFY,
    NOT_LOGGED_IN_TASK_KEYWORDS,
    TASKS_REFERER,
    WEEKLY_CID,
)
from .models import CheckinReport, CheckinStatus, CheckinTaskResult

__all__ = ["CheckinService", "run_checkin"]


# ---------------------------------------------------------------------------
# 签到底层：XML 解析 + 网络请求 + 单任务执行
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RawResponse:
    """单次 plugin.php?actions=job/job2 的解析结果。"""

    action: str
    message: str
    extra: str
    raw_body: str


def _parse_response(raw: str) -> _RawResponse:
    """解析 ``<root>action\\tmessage[\\textra]</root>`` 形态的 XML。

    任何解析失败都把整段 raw 留在 message 里，让调用方走 FAILED 分支。
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


def _request_xml(
    client: httpx.Client,
    *,
    cid: str,
    actions: str,
    base_url: str,
    headers: dict[str, str],
) -> _RawResponse:
    params = {
        "H_name": "tasks",
        "action": "ajax",
        "actions": actions,
        "cid": cid,
        "nowtime": str(int(time.time() * 1000)),
        "verify": DEFAULT_CHECKIN_VERIFY,
    }
    url = f"{base_url}/plugin.php"
    response = client.get(url, params=params, headers=headers)
    response.raise_for_status()
    return _parse_response(response.text)


def _build_headers(cookie_header: str, referer: str) -> dict[str, str]:
    return {
        "Cookie": cookie_header,
        "Referer": referer,
        "Accept-Language": "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
    }


def _format_extra(extra: str) -> str:
    return f"（{extra}）" if extra else ""


def _login_expired_result(label: str, msg: str, raw: str) -> CheckinTaskResult:
    return CheckinTaskResult(
        status=CheckinStatus.FAILED,
        message=f"{label} 失败：Cookie 已失效，请重新 /splogin（站点提示：{msg}）",
        error=raw,
    )


def _already_done_result(label: str) -> CheckinTaskResult:
    """state-C 的统一友好消息——不暴露站点原文，避免"未申请任务!"等
    误导性文案直接抛给用户。"""

    return CheckinTaskResult(
        status=CheckinStatus.ALREADY_DONE,
        message=f"{label}：已签到，请勿重复签到。",
    )


def run_checkin(
    session: SouthPlusSession,
    cookie_header: str,
    *,
    cid: str,
    label: str,
    base_url: str = BBS_BASE_URL,
    referer: str = TASKS_REFERER,
) -> CheckinTaskResult:
    """跑单个签到任务（apply -> collect -> verify），返回详细结果。

    成功的判定标准：collect 自称成功，且二次 apply 命中 state-C 关键字
    （"请勿重复" / "已领取" / "拒离" 等），证明任务真的进了"已完成"列表。
    这对应用户需求"签到必须包括领取，且最终在完成任务界面"。

    任意阶段命中 state-C 关键字（apply 短路 / collect 反查 / verify 确认）
    都收敛到 ALREADY_DONE，并以"请勿重复签到"的友好文案告知用户，不暴露
    站点原文，避免"未申请任务!"这类误导性内容直达用户。
    """
    headers = _build_headers(cookie_header, referer)

    apply_resp = _request_xml(
        session.client,
        cid=cid,
        actions=ACTION_APPLY,
        base_url=base_url,
        headers=headers,
    )

    # 1. 登录失效优先。
    if _matches_any(apply_resp.message, NOT_LOGGED_IN_TASK_KEYWORDS):
        return _login_expired_result(label, apply_resp.message, apply_resp.raw_body)

    # 2. 必须先检查 state-B（NEEDS_COLLECT），再检查 state-C（ALREADY_COLLECTED）。
    #    state-B 文案 "已经申请[日常]完成,请赶紧..." 含 "已经"、"完成" 等
    #    state-C 子串，但带 "请赶紧 / 去完成"——后者只在 state-B 出现。
    if _matches_any(apply_resp.message, APPLY_NEEDS_COLLECT_KEYWORDS):
        pass  # 落到 collect 流程
    elif _matches_any(apply_resp.message, APPLY_ALREADY_COLLECTED_KEYWORDS):
        return _already_done_result(label)
    else:
        return CheckinTaskResult(
            status=CheckinStatus.FAILED,
            message=f"{label} 申请阶段失败：{apply_resp.message or '(空响应)'}",
            error=apply_resp.raw_body,
        )

    # 3. collect。
    collect_resp = _request_xml(
        session.client,
        cid=cid,
        actions=ACTION_COLLECT,
        base_url=base_url,
        headers=headers,
    )
    if _matches_any(collect_resp.message, NOT_LOGGED_IN_TASK_KEYWORDS):
        return _login_expired_result(label, collect_resp.message, collect_resp.raw_body)

    # 必须先于 SUCCESS 检查：state-C 文案 "你[日常]已经完成!" 含 "完成"，
    # 也会被 COLLECT_SUCCESS_KEYWORDS 命中（虽然 SUCCESS 已剔掉"完成"，
    # 但保持先 ALREADY_DONE 后 SUCCESS 的顺序，是稳的）。
    if _matches_any(collect_resp.message, COLLECT_ALREADY_DONE_KEYWORDS):
        return _already_done_result(label)

    if not _matches_any(collect_resp.message, COLLECT_SUCCESS_KEYWORDS):
        return CheckinTaskResult(
            status=CheckinStatus.FAILED,
            message=f"{label} 领取阶段失败：{collect_resp.message or '(空响应)'}",
            error=collect_resp.raw_body,
        )

    # 4. verify：再调一次 apply，期望命中 state-C 关键字，证明任务真的落到了
    #    "已完成"列表。这是站点级别 verify，等价于打开 endtasks 页面后能看到
    #    本次任务。
    verify_resp = _request_xml(
        session.client,
        cid=cid,
        actions=ACTION_APPLY,
        base_url=base_url,
        headers=headers,
    )
    if _matches_any(verify_resp.message, NOT_LOGGED_IN_TASK_KEYWORDS):
        return _login_expired_result(label, verify_resp.message, verify_resp.raw_body)

    if _matches_any(verify_resp.message, APPLY_ALREADY_COLLECTED_KEYWORDS):
        # state-C 验证通过——本次确实从 B 推到了 C。
        return CheckinTaskResult(
            status=CheckinStatus.SUCCESS,
            message=f"{label}：{collect_resp.message}{_format_extra(collect_resp.extra)}",
        )

    # collect 自称成功但 verify 仍要继续 collect / 仍处于 state-B → 实际上没生效。
    return CheckinTaskResult(
        status=CheckinStatus.FAILED,
        message=(
            f"{label} 领取后校验未通过：领取响应「{collect_resp.message}」，"
            f"二次申请仍返回「{verify_resp.message}」，请稍后重试或手动查看。"
        ),
        error=(f"collect={collect_resp.raw_body}\nverify={verify_resp.raw_body}"),
    )


def _safe_run(
    session: SouthPlusSession,
    cookie_header: str,
    *,
    cid: str,
    label: str,
    base_url: str = BBS_BASE_URL,
    referer: str = TASKS_REFERER,
) -> CheckinTaskResult:
    """跑单个任务（apply -> collect -> verify），把异常包成 failed。"""
    try:
        return run_checkin(
            session,
            cookie_header,
            cid=cid,
            label=label,
            base_url=base_url,
            referer=referer,
        )
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


# ---------------------------------------------------------------------------
# 签到门面
# ---------------------------------------------------------------------------


class CheckinService:
    """签到服务门面：日签 cid=15 + 周签 cid=14。

    用法::

        service = CheckinService(session)
        report = service.checkin(cookie_header)
        # report.daily / report.weekly
    """

    def __init__(
        self,
        session: SouthPlusSession,
        *,
        base_url: str | None = None,
        referer: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._referer = referer

    # --- 对外入口 -----------------------------------------------------------

    def checkin(self, cookie_header: str) -> CheckinReport:
        """跑一次完整签到流程。日 + 周两个任务独立尝试，互不影响。"""
        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        daily = self._run_single(cookie_header, cid=DAILY_CID, label="日签")
        weekly = self._run_single(cookie_header, cid=WEEKLY_CID, label="周签")
        return CheckinReport(daily=daily, weekly=weekly)

    def checkin_daily(self, cookie_header: str) -> CheckinTaskResult:
        """单独跑日签（``cid=15``）。已签情况由调用方在 DB 层先过滤。"""
        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        return self._run_single(cookie_header, cid=DAILY_CID, label="日签")

    def checkin_weekly(self, cookie_header: str) -> CheckinTaskResult:
        """单独跑周签（``cid=14``）。"""
        if not cookie_header:
            raise SouthPlusCheckinError("Cookie 为空，无法签到。")
        return self._run_single(cookie_header, cid=WEEKLY_CID, label="周签")

    def _run_single(
        self,
        cookie_header: str,
        *,
        cid: str,
        label: str,
    ) -> CheckinTaskResult:
        kwargs: dict = dict(cid=cid, label=label)
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._referer:
            kwargs["referer"] = self._referer
        return _safe_run(self._session, cookie_header, **kwargs)
