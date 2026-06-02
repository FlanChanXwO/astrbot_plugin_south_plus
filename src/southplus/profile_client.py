"""South Plus 用户资料抓取。

实现根据 ``docs/southplus-capture.md`` 中的 profile.php 截图字段而来。
注意：截图来自 ``bbs.south-plus.org/profile.php``（主域 ``www.south-plus.net``
的 profile 路径布局不同），故本模块硬编码 ``bbs.south-plus.org`` 入口而不复用
``SouthPlusEndpoints.site_base_url``。

鲁棒性策略：

* phpwind 8 系 profile.php 的字段排列稳定但 HTML 没有严格 schema：每次都用
  ``re`` + ``html.unescape`` 抠字段，每个字段独立 try，失败回落到合理默认值
  （0 / 空串），单个字段缺失不影响整体抓取。
* 抓取顶部先 grep "数字ID" / "个人资料" 这种证明已登录的字符串，缺失就抛
  ``SouthPlusProfileError("Cookie 已失效或未登录")``——避免悄悄返回空数据。
* 头像 URL 优先匹配多种可能写法（``faceimg`` / ``avatar`` / ``u.south-plus``
  uploads 目录等），全部失败时回落到一个稳定占位 URL（站点 logo）。
"""

from __future__ import annotations

import html
import re
from dataclasses import fields
from typing import Callable

import httpx

from .models import SouthPlusEndpoints, UserProfile

# bbs.south-plus.org 是用户截图里 profile.php 的真实入口。主域
# www.south-plus.net 的 profile.php 字段布局不同（截图来自 bbs 镜像），
# 本模块只取 bbs.south-plus.org。
BBS_PROFILE_URL = "https://bbs.south-plus.org/profile.php"
BBS_REFERER = "https://bbs.south-plus.org/"

# 没拉到头像时的占位 URL。优先用站点 logo，避免渲染时再去网络拉一次失败。
_FALLBACK_AVATAR_URL = "https://bbs.south-plus.org/images/logo.png"

# 登录态判定关键字。命中其中任何一个就视为 Cookie 失效。
_NOT_LOGGED_IN_KEYWORDS = (
    "还没有登录",
    "暂时不能使用此功能",
    "您没有登录",
    "请先登录",
    "请登录",
)

# 已登录证据关键字。profile.php 渲染成功时必出现"数字ID"或"个人资料"。
_LOGGED_IN_MARKERS = (
    "数字ID",
    "个人资料",
    "会员头衔",
    "在线时间",
)


class SouthPlusProfileError(RuntimeError):
    """profile.php 抓取或解析失败。可向用户展示。"""


class SouthPlusProfileClient:
    """无状态门面：每次 fetch 开一个 httpx.Client。"""

    def __init__(
        self,
        endpoints: SouthPlusEndpoints,
        *,
        http_proxy: str | None = None,
    ) -> None:
        self.endpoints = endpoints
        self.http_proxy = http_proxy or None
        # 允许测试覆盖入口（注入 mock 服务器 URL）。生产路径上一直是
        # ``BBS_PROFILE_URL``。
        self.profile_url = BBS_PROFILE_URL
        self.referer = BBS_REFERER

    def fetch(self, cookie_header: str) -> UserProfile:
        if not cookie_header:
            raise SouthPlusProfileError("Cookie 为空，无法抓取资料。")
        headers = {
            "User-Agent": self.endpoints.user_agent,
            "Cookie": cookie_header,
            "Referer": self.referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=20.0,
            proxy=self.http_proxy,
        ) as client:
            response = client.get(self.profile_url)
        body = response.text
        # phpwind 默认 GBK，httpx 已按 Content-Type 解码；保留 fallback 处理。
        if not body:
            raise SouthPlusProfileError("profile.php 返回空响应。")
        return parse_profile_html(body)


def parse_profile_html(raw_body: str) -> UserProfile:
    """从 profile.php HTML 抠字段。

    抓不到的字段回落 ``UserProfile`` 默认（0 / 空串）。"""

    body = html.unescape(raw_body)

    # 先判失败态。
    for keyword in _NOT_LOGGED_IN_KEYWORDS:
        if keyword in body:
            raise SouthPlusProfileError("Cookie 已失效或未登录")

    # 再判已登录态：profile.php 真实渲染必出现"数字ID"或"个人资料"。
    if not any(marker in body for marker in _LOGGED_IN_MARKERS):
        raise SouthPlusProfileError(
            "未识别到已登录的 profile 页（缺少数字ID/个人资料标记），Cookie 可能已失效。"
        )

    profile = UserProfile()

    # 每个字段独立解析；任何字段失败都回落默认而不抛错。
    _safe_set(profile, "username", body, _parse_username)
    _safe_set(profile, "uid", body, _parse_uid)
    _safe_set(profile, "signature", body, _parse_signature)
    _safe_set(profile, "avatar_url", body, _parse_avatar)
    _safe_set(profile, "title", body, _parse_title)
    _safe_set(profile, "essence", body, _parse_int_field("精华"))
    _safe_set(profile, "posts", body, _parse_int_field("发帖"))
    _safe_set(profile, "hp", body, _parse_int_field("HP"))
    _safe_set(profile, "soul", body, _parse_int_field("魄"))
    _safe_set(profile, "sp_coin", body, _parse_sp_coin)
    _safe_set(profile, "lp", body, _parse_int_field("LP"))
    _safe_set(profile, "online_hours", body, _parse_online_hours)
    _safe_set(profile, "register_date", body, _parse_register_date)
    _safe_set(profile, "last_login_date", body, _parse_last_login_date)

    if not profile.avatar_url:
        profile.avatar_url = _FALLBACK_AVATAR_URL

    return profile


def _safe_set(
    profile: UserProfile,
    field_name: str,
    body: str,
    parser: Callable[[str], object],
) -> None:
    """跑 ``parser(body)``，只在结果非空/非 None 时写回 dataclass。"""

    field_defaults = {f.name: f.default for f in fields(UserProfile)}
    try:
        value = parser(body)
    except Exception:
        return
    if value is None:
        return
    default = field_defaults.get(field_name)
    if isinstance(value, str) and not value:
        # 空字符串视为解析失败，保留默认（也是空串）。
        return
    if value == default:
        return
    setattr(profile, field_name, value)


def _strip_tags(value: str) -> str:
    """去掉 HTML 标签，折叠空白。"""

    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


# --- 字段级 parser ----------------------------------------------------------


def _parse_username(body: str) -> str:
    # phpwind 通常在 <title>用户名 - South Plus</title>，或顶部 "用户名: xxx"。
    patterns = (
        r"<title>\s*([^<\s][^<]*?)\s*[-—]\s*",
        r"用户名[:：]\s*<[^>]*>\s*([^<\s][^<]*?)\s*<",
        r"用户名[:：]\s*([^\s<]+)",
        r"昵\s*称[:：]\s*<[^>]*>\s*([^<\s][^<]*?)\s*<",
    )
    return _first_match(body, patterns)


def _parse_uid(body: str) -> str:
    patterns = (
        r"数字\s*ID[:：]\s*<[^>]*>?\s*(\d+)",
        r"数字\s*ID[:：]\s*(\d+)",
        r"\bUID[:：]\s*<[^>]*>?\s*(\d+)",
        r"\bUID[:：]\s*(\d+)",
        r"uid=(\d+)",
    )
    return _first_match(body, patterns)


def _parse_signature(body: str) -> str:
    # 个性签名后面可能跟一整段 HTML，截到下一段空行/标签结束。
    patterns = (
        r"个性签名[:：]\s*<[^>]*>([^<]{0,200})<",
        r"个性签名[:：]\s*([^<\n\r]{1,200})",
    )
    raw = _first_match(body, patterns)
    if not raw:
        return ""
    return _strip_tags(raw)


def _parse_avatar(body: str) -> str:
    # 头像可能写法很多：
    #   <img src="...faceimg..."
    #   <img class="avatar" src="..."
    #   pw_ajax.php?action=ajax&_user_face_=
    #   uploadface/.../xxx.jpg
    patterns = (
        r'<img[^>]+src="([^"]*(?:faceimg|uploadface|avatar)[^"]*)"',
        r'<img[^>]+class="[^"]*avatar[^"]*"[^>]+src="([^"]+)"',
        r'src="([^"]+)"[^>]*alt="(?:头像|avatar)"',
        r'<img[^>]+src="(https?://[^"]+/u\.south-plus[^"]+\.(?:jpg|png|gif))"',
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            url = match.group(1).strip()
            if url:
                return url
    return ""


def _parse_title(body: str) -> str:
    # 会员头衔 / 用户组等。截图上是 "Lv.0"。
    patterns = (
        r"会员头衔[:：]\s*<[^>]*>([^<]{1,40})<",
        r"会员头衔[:：]\s*([^<\n\r]{1,40})",
        r"用户组[:：]\s*<[^>]*>([^<]{1,40})<",
        r"用户组[:：]\s*([^<\n\r]{1,40})",
    )
    raw = _first_match(body, patterns)
    return _strip_tags(raw) if raw else ""


def _parse_int_field(label: str) -> Callable[[str], int]:
    """生成 ``r'<label>[:：]\\s*<[^>]*>?(\\d+)'`` 风格匹配器。"""

    label_pat = re.escape(label)
    patterns = (
        rf"{label_pat}\s*[:：]\s*<[^>]*>?\s*(-?\d+)",
        rf"{label_pat}\s*[:：]\s*(-?\d+)",
        rf"{label_pat}[^0-9-]{{0,40}}(-?\d+)",
    )

    def _parse(body: str) -> int:
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return 0

    return _parse


def _parse_sp_coin(body: str) -> str:
    # 截图：SP币: 14 G。保留 "14 G" 字符串原样。
    patterns = (
        r"SP\s*币\s*[:：]\s*<[^>]*>?\s*([0-9.,]+\s*[A-Za-z]+)",
        r"SP\s*币\s*[:：]\s*([0-9.,]+\s*[A-Za-z]+)",
        r"SP\s*币\s*[:：]\s*([0-9.,]+)",
    )
    raw = _first_match(body, patterns)
    return raw.strip() if raw else ""


def _parse_online_hours(body: str) -> str:
    patterns = (
        r"在线时间\s*[:：]\s*<[^>]*>?\s*([0-9.,]+\s*小时)",
        r"在线时间\s*[:：]\s*([0-9.,]+\s*小时)",
        r"在线时间\s*[:：]\s*([0-9.,]+)",
    )
    raw = _first_match(body, patterns)
    return raw.strip() if raw else ""


def _parse_register_date(body: str) -> str:
    return _parse_date_field(body, ("注册时间", "注册日期"))


def _parse_last_login_date(body: str) -> str:
    return _parse_date_field(body, ("最后登录", "最近登录", "上次登录"))


def _parse_date_field(body: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        label_pat = re.escape(label)
        patterns = (
            rf"{label_pat}\s*[:：]\s*<[^>]*>?\s*(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}})",
            rf"{label_pat}\s*[:：]\s*(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}})",
            rf"{label_pat}[^0-9]{{0,40}}(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}})",
        )
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                return _normalize_date(match.group(1))
    return ""


def _normalize_date(raw: str) -> str:
    parts = re.split(r"[-/]", raw)
    if len(parts) != 3:
        return raw
    try:
        y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return raw
    return f"{y:04d}-{m:02d}-{d:02d}"


def _first_match(body: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return ""
