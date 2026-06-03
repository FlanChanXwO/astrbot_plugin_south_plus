"""签到客户端测试。

用本地 HTTP server 模拟 ``plugin.php?H_name=tasks&action=ajax&...``，
覆盖：

* 完整 apply -> collect 成功路径（日/周各一）。
* apply 阶段返回 "已完成" 直接落 ALREADY_DONE。
* collect 阶段返回错误关键字落 FAILED 并把原文塞 error。
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
    CheckinStatus,
    SouthPlusCheckinClient,
    SouthPlusCheckinError,
    SouthPlusEndpoints,
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


def _make_client(base_url: str) -> SouthPlusCheckinClient:
    return SouthPlusCheckinClient(_endpoints(base_url), base_url=base_url)


def _xml(text: str) -> bytes:
    return f"<root><![CDATA[{text}]]></root>".encode("utf-8")


@pytest.fixture()
def mock_tasks_server() -> Iterator[
    tuple[str, dict[tuple[str, str], bytes], list[dict[str, str]]]
]:
    """启动 mock plugin.php server。

    ``responses`` 是 ``(cid, actions) -> body`` 的 dict，测试在 fixture
    返回值里改 mapping 来注入不同响应。``requests`` 是命中过的请求列表，
    便于断言调用次数 / 顺序。
    """

    responses: dict[tuple[str, str], bytes] = {}
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
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t申请成功，请前往完成任务")
    responses[("15", "job2")] = _xml("ok\t已完成日常任务并领取奖励\t10 G")
    responses[("14", "job")] = _xml("ok\t周常任务申请成功")
    responses[("14", "job2")] = _xml("ok\t已完成周常任务并领取奖励\t50 G")

    report = _make_client(base_url).checkin("eb9e6_winduser=foo")

    assert report.daily.status is CheckinStatus.SUCCESS
    assert "日签" in report.daily.message and "10 G" in report.daily.message
    assert report.weekly.status is CheckinStatus.SUCCESS
    assert "周签" in report.weekly.message and "50 G" in report.weekly.message
    # 4 次请求：日 apply、日 collect、周 apply、周 collect。
    actions = [(r["cid"], r["actions"]) for r in requests]
    assert actions == [("15", "job"), ("15", "job2"), ("14", "job"), ("14", "job2")]
    # nowtime 必须是毫秒整数。
    for req in requests:
        assert req["nowtime"].isdigit() and len(req["nowtime"]) >= 10


def test_apply_already_done_skips_collect(mock_tasks_server) -> None:
    base_url, responses, requests = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t今天已经完成过该任务")
    responses[("14", "job")] = _xml("ok\t本周已经完成过该任务")
    # collect 故意不注册——任何一次命中都说明 apply 没有提前退出。

    report = _make_client(base_url).checkin("cookie")

    assert report.daily.status is CheckinStatus.ALREADY_DONE
    assert "已经" in report.daily.message
    assert report.weekly.status is CheckinStatus.ALREADY_DONE
    # 只有 2 次请求，没有调用 job2。
    actions = {(r["cid"], r["actions"]) for r in requests}
    assert actions == {("15", "job"), ("14", "job")}


def test_collect_failure_preserves_raw(mock_tasks_server) -> None:
    base_url, responses, _ = mock_tasks_server
    responses[("15", "job")] = _xml("ok\t申请成功")
    responses[("15", "job2")] = _xml("error\t任务条件未满足")
    responses[("14", "job")] = _xml("ok\t申请成功")
    responses[("14", "job2")] = _xml("error\t任务条件未满足")

    report = _make_client(base_url).checkin("cookie")

    assert report.daily.status is CheckinStatus.FAILED
    assert "任务条件未满足" in report.daily.message
    assert "任务条件未满足" in report.daily.error
    assert report.weekly.status is CheckinStatus.FAILED


def test_invalid_xml_falls_back_to_failed(mock_tasks_server) -> None:
    base_url, responses, _ = mock_tasks_server
    responses[("15", "job")] = b"<<<not xml at all>>>"
    responses[("14", "job")] = b"<<<not xml at all>>>"

    report = _make_client(base_url).checkin("cookie")

    # apply 阶段消息体是 "<<<not xml at all>>>"，命中不到任何成功关键字，
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
    responses[("15", "job")] = _xml("ok\t申请成功")
    responses[("15", "job2")] = _xml("ok\t完成日常\t5 G")

    result = _make_client(base_url).checkin_daily("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert {r["cid"] for r in requests} == {"15"}


def test_checkin_weekly_only(mock_tasks_server) -> None:
    base_url, responses, requests = mock_tasks_server
    responses[("14", "job")] = _xml("ok\t申请成功")
    responses[("14", "job2")] = _xml("ok\t完成周常\t20 G")

    result = _make_client(base_url).checkin_weekly("cookie")

    assert result.status is CheckinStatus.SUCCESS
    assert {r["cid"] for r in requests} == {"14"}
