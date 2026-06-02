"""South Plus 登录 HTTP 调用。

实现根据 docs/southplus-capture.md 的"当前抓包结果"小节而来。修改前请先重新跑
一遍 docs/southplus-capture.md 的抓包流程，确认改动只反映站点真实变化。
"""

from __future__ import annotations

import time

import httpx

from .constants import (
    DEFAULT_FORM_FORWARD,
    DEFAULT_FORM_STEP,
    DEFAULT_FORM_SUBMIT,
    DEFAULT_VERIFY_PATH,
    FAILURE_KEYWORDS,
    LOGIN_COOKIE_NAME_SUFFIXES,
)
from .models import CaptchaPayload, LoginRequest, LoginResult, SouthPlusEndpoints


class SouthPlusLoginError(RuntimeError):
    """South Plus 登录流程中产生的可向用户展示的错误。"""


class SouthPlusClient:
    """无状态门面：每次登录调用 ``new_attempt()`` 拿一个独立 httpx.Client 会话。"""

    def __init__(self, endpoints: SouthPlusEndpoints, *, http_proxy: str = "") -> None:
        self.endpoints = endpoints
        self.http_proxy = http_proxy or None

    def new_attempt(self) -> SouthPlusLoginAttempt:
        return SouthPlusLoginAttempt(self.endpoints, http_proxy=self.http_proxy)

    def check_cookie(self, cookie: str) -> str:
        if not cookie:
            raise SouthPlusLoginError("Cookie 为空，无法校验。")
        headers = {
            "User-Agent": self.endpoints.user_agent,
            "Cookie": cookie,
            "Referer": self.endpoints.site_base_url + "/",
        }
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=20.0,
            proxy=self.http_proxy,
        ) as client:
            response = client.get(self.endpoints.verify_url)
            body = response.text
        if _looks_login_page(response.url, body):
            raise SouthPlusLoginError("Cookie 未通过登录态校验，可能已失效。")
        return cookie


class SouthPlusLoginAttempt:
    """单次登录会话：保持 cookie jar 跨 captcha + submit 一致。"""

    def __init__(
        self, endpoints: SouthPlusEndpoints, *, http_proxy: str | None = None
    ) -> None:
        self.endpoints = endpoints
        self._client = httpx.Client(
            headers={
                "User-Agent": endpoints.user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            timeout=20.0,
            proxy=http_proxy,
        )
        self._login_page_loaded = False

    def __enter__(self) -> SouthPlusLoginAttempt:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        del exc_type, exc_val, exc_tb
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_captcha(self) -> CaptchaPayload:
        self._ensure_login_page()
        # 抓包结论：phpwind 的 opencode JS 把 <img> 的 src 改成
        # `ck.php?nowtime=<毫秒时间戳>`。South Plus 用这个 query 形态区分
        # "前端真用户点开验证码 vs 后端直接探测"——只有带 nowtime 的请求
        # 才返回清晰验证码，其它形态都返回浅色水印背景。
        nowtime = str(int(time.time() * 1000))
        response = self._client.get(
            self.endpoints.captcha_url,
            params={"nowtime": nowtime},
            headers={
                "Referer": self.endpoints.login_url,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        if "image" not in content_type and not response.content.startswith(b"\x89PNG"):
            raise SouthPlusLoginError(
                f"验证码响应不是图片：content-type={content_type}"
            )
        return CaptchaPayload(content_type=content_type, body=response.content)

    def submit(self, request: LoginRequest) -> LoginResult:
        self._ensure_login_page()
        payload = {
            "forward": DEFAULT_FORM_FORWARD,
            "jumpurl": self.endpoints.site_base_url + "/" + DEFAULT_VERIFY_PATH,
            "step": DEFAULT_FORM_STEP,
            "gdcode": request.captcha,
            "lgt": request.login_type,
            "pwuser": request.username,
            "pwpwd": request.password,
            "hideid": request.hide_id,
            "cktime": request.cookie_ttl,
            "submit": DEFAULT_FORM_SUBMIT,
        }
        response = self._client.post(
            self.endpoints.login_url,
            data=payload,
            headers={
                "Referer": self.endpoints.login_url,
                "Origin": self.endpoints.site_base_url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        body = response.text
        cookie_header = _cookie_header(self._client, self.endpoints.cookie_domains)

        if _has_phpwind_login_cookie(self._client):
            return LoginResult(
                username=request.username,
                cookie=cookie_header,
                message="登录成功，Cookie 已保存。",
            )

        raise SouthPlusLoginError(_classify_failure(body))

    def verify(self, cookie_header: str) -> bool:
        response = self._client.get(
            self.endpoints.verify_url,
            headers={
                "Cookie": cookie_header,
                "Referer": self.endpoints.site_base_url + "/",
            },
        )
        return not _looks_login_page(response.url, response.text)

    def _ensure_login_page(self) -> None:
        if self._login_page_loaded:
            return
        response = self._client.get(
            self.endpoints.login_url,
            headers={"Referer": self.endpoints.site_base_url + "/"},
        )
        response.raise_for_status()
        self._login_page_loaded = True


def _cookie_header(client: httpx.Client, allowed_domains: tuple[str, ...]) -> str:
    items: list[tuple[str, str]] = []
    for cookie in client.cookies.jar:
        domain = (cookie.domain or "").lstrip(".").lower()
        if allowed_domains and not _domain_matches(domain, allowed_domains):
            continue
        items.append((cookie.name, cookie.value or ""))
    return "; ".join(f"{name}={value}" for name, value in items)


def _domain_matches(domain: str, allowed: tuple[str, ...]) -> bool:
    if not domain:
        return False
    for allow in allowed:
        if domain == allow or domain.endswith("." + allow):
            return True
    return False


def _has_phpwind_login_cookie(client: httpx.Client) -> bool:
    # 抓包结论：phpwind 站点登录成功后会下发 `<prefix>_winduser` / `<prefix>_winduid`
    # cookie；其中 `<prefix>` 是站点 hash（南+主站当前为 `eb9e6`）。
    for cookie in client.cookies.jar:
        for suffix in LOGIN_COOKIE_NAME_SUFFIXES:
            if cookie.name.endswith(suffix):
                return True
    return False


def _looks_login_page(url: object, body: str) -> bool:
    url_str = str(url or "")
    if "login.php" in url_str:
        return True
    if "登录" in body and "退出" not in body:
        return True
    return False


def _classify_failure(body: str) -> str:
    # 抓包结论：失败时 South Plus 返回 200 + 中文错误文案，没有结构化错误码。
    # 关键字顺序决定优先级，遇到验证码相关关键字立刻报错给用户重填验证码。
    for keyword, message in FAILURE_KEYWORDS:
        if keyword in body:
            return message
    return "登录失败，站点未返回登录态 cookie。可能账号、密码或验证码错误。"
