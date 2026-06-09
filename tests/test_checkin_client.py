"""签到客户端测试。

用本地 HTTP server 模拟 ``plugin.php?H_name=tasks&action=ajax&...``，
覆盖 apply -> collect -> verify 三段流程的状态机：

* 完整 apply -> collect -> verify 成功路径（日 / 周各一）。
* apply 阶段返回 state-C 关键字（"请勿重复" / "已领取" / "拒离上次申请...
  还没超过 18 小时" / "本周已完成"）直接落 ALREADY_DONE，给用户友好的
  "请勿重复签到"提示，不暴露站点原文。
* apply 返回 state-B 文案 "已经申请[日常]完成,请赶紧去完成任务吧!"——必须继续
  跑 collect + verify，不能短路成 ALREADY_DONE。
* apply 已进入 state-B 后，collect 返回 state-C 旁路文案
  "你[日常]已经完成!" / "未申请任务!" → 继续 verify；verify 确认 state-C 后
  计入 SUCCESS。
* collect 成功但 verify 仍返回 state-B → 视为没真正生效，落 FAILED。
* 任务接口返回"还没有登录" / "暂时不能使用此功能" → 立即落 FAILED 提示重新登录。
* XML parse 失败回落 FAILED 不抛。
* 网络错误回落 FAILED 不抛。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from src.southplus.api import (
    CheckinService,
    CheckinStatus,
    SouthPlusCheckinError,
    SouthPlusEndpoints,
    SouthPlusSession,
)


def _endpoints(base_url: str) -> SouthPlusEndpoints:
    return SouthPlusEndpoints(
        site_base_url=base_url,
        login_url=f"{base_url}/login.php",
        captcha_url=f"{base_url}/ck.php",
        verify_url=f"{base_url}/index.php",
        cookie_domains=("127.0.0.1",),
        user_agent="pytest-southplus",
    )


def _make_client(base_url: str) -> CheckinService:
    return CheckinService(SouthPlusSession(_endpoints(base_url)), base_url=base_url)


def _xml(text: str) -> bytes:
    return f"<root><![CDATA[{text}]]></root>".encode("utf-8")


# verify 阶段 = 再调一次 apply。mock 同一 (cid, "job") 只能返回一种响应，因此
# 通过命中计数器在第 2 次命中时切换到 "请勿重复" / 自定义响应。
class _CountedBody:
    """支持按命中次数返回不同响应的 mock body。"""

    def __init__(self, sequence: list[bytes]) -> None:
        self._sequence = sequence
        self._index = 0

    def __call__(self) -> bytes:
        body = self._sequence[min(self._index, len(self._sequence) - 1)]
        self._index += 1
        return body


@pytest.fixture()
def mock_tasks_server() -> Iterator[
    tuple[str, dict[tuple[str, str], object], list[dict[str, str]]]
]:
    """启动 mock plugin.php server。

    ``responses`` 的 value 可以是：

    * ``bytes`` → 每次请求都返回同一段 body；
    * ``_CountedBody`` → 按命中次数返回不同 body（用于 verify 第二次 apply 切换）；
    * 任何 callable → 每次命中调用一次拿 body。
    """

    responses: dict[tuple[str, str], object] = {}
    requests: list[dict[str, str]] = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/plugin.php":
                self._send(HTTPStatus.NOT_FOUND, b"")
                return
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            requests.append(params)
            key = (params.get("cid", ""), params.get("actions", ""))
            body = responses.get(key)
            if body is None:
                self._send(HTTPStatus.OK, _xml("error\t未知任务"))
                return
            if callable(body):
                body = body()
            assert isinstance(body, bytes)
            self._send(HTTPStatus.OK, body)

        def _send(self, status: HTTPStatus, body: bytes) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, responses, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# --- 测试 -------------------------------------------------------------------


def test_checkin_empty_cookie_raises() -> None:
    client = _make_client("http://127.0.0.1:1")
    with pytest.raises(SouthPlusCheckinError):
        client.checkin(cookie_header="")


def test_full_success_path(mock_tasks_server) -> None:
    """apply -> collect -> verify 全部通过，最终落 SUCCESS。"""
    base_url, responses, requests = mock_tasks_server
    # 日签：apply 进 state B；collect 进 state C；verify 再调 apply → "请勿重复"
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t完成[日常]任务,获得奖励\t10 G")
    responses[("14", "job")] = _CountedBody(
        [
            _xml("ok\t申请[周常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("14", "job2")] = _xml("ok\t完成[周常]任务,获得奖励\t50 G")

    report = _make_client(base_url).checkin("eb9e6_winduser=foo")

    assert report.daily.status is CheckinStatus.SUCCESS
    assert "日签" in report.daily.message and "10 G" in report.daily.message
    assert report.weekly.status is CheckinStatus.SUCCESS
    assert "周签" in report.weekly.message and "50 G" in report.weekly.message
    # 每个 cid 6 次：apply、collect、verify-apply。日先于周。
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [
        ("15", "job"),
        ("15", "job2"),
        ("15", "job"),
        ("14", "job"),
        ("14", "job2"),
        ("14", "job"),
    ]
    # nowtime 必须是毫秒整数。
    for req in requests:
        assert req["nowtime"].isdigit() and len(req["nowtime"]) >= 10


def test_apply_state_c_skips_collect(mock_tasks_server) -> None:
    """apply 阶段命中 state-C 关键字时跳过 collect / verify，给友好提示。"""
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t今天已完成任务,请勿重复申请!")
    responses[("14", "job")] = _xml("ok\t本周已完成签到任务,请勿重复申请!")
    # collect / verify 故意不注册——命中任何说明 apply 没短路。

    report = _make_client(base_url).checkin("cookie")

    assert report.daily.status is CheckinStatus.ALREADY_DONE
    assert "请勿重复签到" in report.daily.message
    # 必须避免把站点原文（含"未申请"、"请勿重复申请"等）直抛给用户。
    assert "未申请" not in report.daily.message
    assert report.weekly.status is CheckinStatus.ALREADY_DONE
    assert "请勿重复签到" in report.weekly.message
    actions = {(r["cid"], r["actions"]) for r in requests}
    assert actions == {("15", "job"), ("14", "job")}


def test_apply_cooldown_returns_already_done(mock_tasks_server) -> None:
    """apply 阶段返回 18 小时冷却拒绝 → state-C，落 ALREADY_DONE。

    抓包文案："拒离上次申请[日常]还没超过 18 小时"。注意该串含 "申请["
    子串——以前会被错误归到 APPLY_NEEDS_COLLECT_KEYWORDS。
    """

    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t拒离上次申请[日常]还没超过 18 小时")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.ALREADY_DONE
    assert "请勿重复签到" in result.message
    # 关键：只跑了 apply 一次，没误打到 collect。
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job")]


def test_apply_already_applied_still_runs_collect_and_verify(mock_tasks_server) -> None:
    """用户报告的具体回归：apply 返回 "已经申请[日常]完成,请赶紧去完成任务吧!"

    这是 state B（已申请未领取），必须继续 collect + verify，不能短路成
    ALREADY_DONE。
    """
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t已经申请[日常]完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t完成[日常]任务,获得奖励\t10 G")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.SUCCESS
    # 三次请求：apply / collect / verify-apply。
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job"), ("15", "job2"), ("15", "job")]


def test_collect_says_already_completed_after_apply_state_b_verifies_success(
    mock_tasks_server,
) -> None:
    """apply 已进入 state-B 后，collect 的 state-C 文案也属于本轮成功。

    关键区别：如果 apply 一开始就是 state-C，说明本轮开始前已签，仍是
    ALREADY_DONE；但 apply 已经把任务推入/确认在 state-B 后，collect 再返回
    "已经完成" 且 verify 确认 state-C，应计入本轮 SUCCESS。
    """

    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t你[日常]已经完成!")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert "已确认完成" in result.message
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job"), ("15", "job2"), ("15", "job")]


def test_collect_says_not_applied_after_apply_state_b_verifies_success(
    mock_tasks_server,
) -> None:
    """apply 已进入 state-B 后，collect 的 "未申请" 需靠 verify 判定。

    phpwind 会在任务已离开进行中列表时返回 "未申请任务!"；只要 verify 再次
    apply 能确认 state-C，就说明本轮有效流程已经把结果推到完成态。
    """
    base_url, responses, requests = mock_tasks_server
    responses[("14", "job")] = _CountedBody(
        [
            _xml("ok\t申请[周常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t本周已完成签到任务,请勿重复申请!"),
        ]
    )
    responses[("14", "job2")] = _xml("ok\t未申请任务!\t14")

    result = _make_client(base_url).checkin_weekly("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert "已确认完成" in result.message
    # 不能把站点原文 "未申请任务" 直抛给用户。
    assert "未申请" not in result.message
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("14", "job"), ("14", "job2"), ("14", "job")]


def test_collect_already_done_but_verify_not_terminal_returns_failed(
    mock_tasks_server,
) -> None:
    """collect 命中 state-C 旁路，但 verify 未确认完成时必须失败。

    这条锁定 ``collect_confirmed_terminal=True`` 的负路径：失败提示应使用
    归一化后的"已确认完成"，但不能把 verify 未达 state-C 误当成功。
    """
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t已经申请[日常]完成,请赶紧去完成任务吧!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t你[日常]已经完成!")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.FAILED
    assert "校验未通过" in result.message
    assert "已确认完成" in result.message
    assert "你[日常]已经完成" not in result.message
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job"), ("15", "job2"), ("15", "job")]


def test_collect_success_but_verify_state_b_returns_failed(mock_tasks_server) -> None:
    """collect 自报成功但 verify 仍处于 state-B → 真实没生效，落 FAILED。"""
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!"),
            # verify 阶段仍说"请赶紧去完成"——state-C 未达成。
            _xml("ok\t已经申请[日常]完成,请赶紧去完成任务吧!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t完成[日常]任务,获得奖励\t10 G")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.FAILED
    assert "校验未通过" in result.message
    # 三次都打到了，证明 verify 真的有跑。
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job"), ("15", "job2"), ("15", "job")]


def test_collect_failure_preserves_raw(mock_tasks_server) -> None:
    base_url, responses, _ = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!")
    responses[("15", "job2")] = _xml("error\t任务条件未满足")
    responses[("14", "job")] = _xml("ok\t申请[周常]任务完成,请赶紧去完成任务吧!")
    responses[("14", "job2")] = _xml("error\t任务条件未满足")

    report = _make_client(base_url).checkin("cookie")

    assert report.daily.status is CheckinStatus.FAILED
    assert "任务条件未满足" in report.daily.message
    assert "任务条件未满足" in report.daily.error
    assert report.weekly.status is CheckinStatus.FAILED


def test_login_expired_returns_failed_with_hint(mock_tasks_server) -> None:
    base_url, responses, _ = mock_tasks_server
    responses[("15", "job")] = _xml("err\t您还没有登录或注册，暂时不能使用此功能!!")
    responses[("14", "job")] = _xml("err\t您还没有登录或注册，暂时不能使用此功能!!")

    report = _make_client(base_url).checkin("cookie")

    assert report.daily.status is CheckinStatus.FAILED
    assert "Cookie 已失效" in report.daily.message
    assert "splogin" in report.daily.message
    assert report.weekly.status is CheckinStatus.FAILED


def test_invalid_xml_falls_back_to_failed(mock_tasks_server) -> None:
    base_url, responses, _ = mock_tasks_server
    responses[("15", "job")] = b"<<<not xml at all>>>"
    responses[("14", "job")] = b"<<<not xml at all>>>"

    report = _make_client(base_url).checkin("cookie")

    # apply 阶段消息体是 "<<<not xml at all>>>"，命中不到任何关键字，
    # 直接 FAILED。
    assert report.daily.status is CheckinStatus.FAILED
    assert report.weekly.status is CheckinStatus.FAILED


def test_network_error_returns_failed_not_raise() -> None:
    # 1 端口几乎肯定不通；测试 _safe_run 把 httpx.HTTPError 吃掉。
    client = _make_client("http://127.0.0.1:1")
    report = client.checkin("cookie")
    assert report.daily.status is CheckinStatus.FAILED
    assert "网络" in report.daily.message or "httpx" in report.daily.error
    assert report.weekly.status is CheckinStatus.FAILED


def test_checkin_daily_only(mock_tasks_server) -> None:
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _CountedBody(
        [
            _xml("ok\t申请[日常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("15", "job2")] = _xml("ok\t完成[日常]任务,获得奖励\t5 G")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert {r["cid"] for r in requests} == {"15"}


def test_checkin_weekly_only(mock_tasks_server) -> None:
    base_url, responses, requests = mock_tasks_server
    responses[("14", "job")] = _CountedBody(
        [
            _xml("ok\t申请[周常]任务完成,请赶紧去完成任务吧!"),
            _xml("ok\t请勿重复申请,该任务已完成!"),
        ]
    )
    responses[("14", "job2")] = _xml("ok\t完成[周常]任务,获得奖励\t20 G")

    result = _make_client(base_url).checkin_weekly("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert {r["cid"] for r in requests} == {"14"}
