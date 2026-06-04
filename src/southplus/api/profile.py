"""South Plus 用户资料抓取与解析。

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
* 头像按 ``.pic > img`` 的 phpwind 结构定位（即 ``class="pic"`` 块下紧跟着
  ``<img src="...">``），失败时回落到几种历史写法（``faceimg`` / ``avatar`` /
  ``u.south-plus`` 域名）。所有相对 URL 会被 absolutize 到 bbs.south-plus.org。
"""

from __future__ import annotations

import html
import re
from dataclasses import fields
from typing import Callable
from urllib.parse import urljoin

from ..client import SouthPlusSession
from ..exceptions import SouthPlusProfileError
from .constants import (
    BBS_BASE_URL,
    BBS_PROFILE_URL,
    BBS_REFERER,
    FALLBACK_AVATAR_URL,
    LOGGED_IN_MARKERS,
    NOT_LOGGED_IN_KEYWORDS,
)
from ..models import UserProfile

__all__ = ["SouthPlusProfileApi", "parse_profile_html"]


class SouthPlusProfileApi:
    """profile.php 抓取门面：使用共享 ``httpx.Client`` 走代理。"""

    def __init__(self, session: SouthPlusSession) -> None:
        self.session = session
        # 允许测试覆盖入口（注入 mock 服务器 URL）。生产路径上一直是
        # ``BBS_PROFILE_URL``。
        self.profile_url = BBS_PROFILE_URL
        self.referer = BBS_REFERER

    def fetch(self, cookie_header: str) -> UserProfile:
        if not cookie_header:
            raise SouthPlusProfileError("Cookie 为空，无法抓取资料。")
        headers = {
            "Cookie": cookie_header,
            "Referer": self.referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        response = self.session.client.get(self.profile_url, headers=headers)
        body = response.text
        # phpwind 默认 GBK，httpx 已按 Content-Type 解码；保留 fallback 处理。
        if not body:
            raise SouthPlusProfileError("profile.php 返回空响应。")
        return parse_profile_html(body)

    def fetch_avatar(self, avatar_url: str) -> bytes | None:
        """复用同样的代理/UA/Referer 配置去拉头像图字节。

        失败时返回 ``None``，调用方（卡片渲染）应回落到占位实现。
        """

        if not avatar_url:
            return None
        headers = {
            "Referer": self.referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            response = self.session.client.get(
                avatar_url, headers=headers, timeout=10.0
            )
            if response.status_code == 200 and response.content:
                return response.content
        except Exception:  # noqa: BLE001
            return None
        return None


def parse_profile_html(raw_body: str) -> UserProfile:
    """从 profile.php HTML 抠字段。

    抓不到的字段回落 ``UserProfile`` 默认（0 / 空串）。"""

    body = html.unescape(raw_body)

    # 先判失败态。
    for keyword in NOT_LOGGED_IN_KEYWORDS:
        if keyword in body:
            raise SouthPlusProfileError("Cookie 已失效或未登录")

    # 再判已登录态：profile.php 真实渲染必出现"数字ID"或"个人资料"。
    if not any(marker in body for marker in LOGGED_IN_MARKERS):
        raise SouthPlusProfileError(
            "未识别到已登录的 profile 页（缺少数字ID/个人资料标记），Cookie 可能已失效。"
        )

    profile = UserProfile()

    # 先抠 uid——username 的解析依赖 "(数字ID:xxx)" 邻接，知道 uid 后能精准
    # 截 username。
    _safe_set(profile, "uid", body, _parse_uid)
    _safe_set(profile, "username", body, _parse_username_factory(profile.uid))
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

    profile.avatar_url = _absolutize_url(profile.avatar_url) or FALLBACK_AVATAR_URL

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


def _absolutize_url(url: str) -> str:
    """把可能的相对 URL 拼成绝对 URL。"""

    if not url:
        return ""
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    return urljoin(BBS_BASE_URL + "/", url.lstrip("/"))


# --- 字段级 parser ----------------------------------------------------------


def _parse_username_factory(uid: str) -> Callable[[str], str]:
    """phpwind profile.php 顶端排版是 ``username (数字ID:UID) 编辑资料``。

    用 UID 锚定能精准抠出 username。phpwind 模板里 username 和 "(数字ID:...)"
    之间常被 ``</a><span>`` 之类的 inline 标签隔开，所以先 ``_strip_tags`` 把
    HTML 折成纯文本再做邻接匹配，避免逐个枚举标签嵌套形态。UID 抓不到时
    退回到几种带标签的兜底匹配。
    """

    def _parse(body: str) -> str:
        if uid:
            # 标签 -> 空格，避免 ``<p>个人资料</p><h2>flanchan</h2>`` 折叠后
            # 黏在一起拿不出干净 token。
            plain = re.sub(r"<[^>]+>", " ", body)
            plain = re.sub(r"\s+", " ", plain).strip()
            uid_pat = re.escape(uid)
            # 取 ``(数字ID:UID)`` 之前最近的一个非空白 token。
            pattern = rf"([^\s()<>]+)\s*\(\s*数字\s*ID\s*[:：]\s*{uid_pat}\s*\)"
            match = re.search(pattern, plain)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate
        # 兜底：phpwind v8/v9 在 ``<title>用户名 - South Plus</title>`` 也有
        # 一份，但部分镜像 title 是"用户信息"，命中率较低。
        patterns_fallback = (
            r"用户名[:：]\s*<[^>]*>\s*([^<\s][^<]*?)\s*<",
            r"用户名[:：]\s*([^\s<]+)",
            r"昵\s*称[:：]\s*<[^>]*>\s*([^<\s][^<]*?)\s*<",
        )
        return _first_match(body, patterns_fallback)

    return _parse


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
    """phpwind ``.pic > img`` 是头像首选位置。

    `.pic` 在 phpwind 模板里可能是 ``<div>`` / ``<td>`` / ``<dt>``，所以正则
    只锚定 ``class="...pic..."`` 后紧跟着的 ``<img src=...>``，允许中间穿插
    一个 ``<a>`` 跳转包裹。
    """

    patterns = (
        # .pic > img：phpwind profile.php 用户提示的首选选择器。
        r'class="[^"]*\bpic\b[^"]*"[^>]*>\s*(?:<a[^>]*>\s*)?<img[^>]+src="([^"]+)"',
        # 历史兜底：旧模板里头像 src 含 ``faceimg`` / ``uploadface`` / ``avatar`` 关键字。
        r'<img[^>]+src="([^"]*(?:faceimg|uploadface|avatar)[^"]*)"',
        r'<img[^>]+class="[^"]*avatar[^"]*"[^>]+src="([^"]+)"',
        # 站内上传域。
        r'<img[^>]+src="(https?://[^"]+/u\.south-plus[^"]+\.(?:jpg|png|gif))"',
        # alt="头像" 标记。
        r'src="([^"]+)"[^>]*alt="(?:头像|avatar)"',
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
