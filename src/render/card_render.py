"""HTML + t2i 用户资料卡片渲染。"""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from astrbot.core import html_renderer

from ..southplus.api import UserProfile

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_RESOURCES_DIR = _PLUGIN_ROOT / "resources"
_CARD_CLIP_WIDTH = 420
_CARD_VERTICAL_GUTTER = 40
_CARD_BASE_HEIGHT = 211
_CARD_SIGNATURE_HEIGHT = 25
_CARD_STATS_ITEM_HEIGHT = 43
_CARD_STATS_DIVIDER_HEIGHT = 23
_CARD_INFO_ROW_HEIGHT = 32
# Playwright 实测截图场景下手算高度比卡片底部少约 9px；
# 贴住卡片底边裁剪，避免末尾露出页面背景色横条。
_CARD_CLIP_HEIGHT_GUARD = 9

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)


def _to_data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _load_logo_data_uri() -> str | None:
    logo_path = _RESOURCES_DIR / "logo-spring-south.png"
    if not logo_path.exists():
        return None
    return _to_data_uri(logo_path.read_bytes())


def _profile_card_clip_height(ctx: dict[str, str | None]) -> int:
    """按模板可见项计算截图高度，避免 t2i 截取默认视口下方空白。"""
    has_signature = bool(ctx["signature"])
    stat_count = sum(
        (
            bool(ctx["hp"] and ctx["hp"] != "0"),
            bool(ctx["sp_coin"]),
            bool(ctx["soul"] and ctx["soul"] != "0"),
        )
    )
    info_count = sum(
        (
            bool(ctx["essence"] and ctx["essence"] != "0"),
            bool(ctx["posts"] and ctx["posts"] != "0"),
            bool(ctx["lp"] and ctx["lp"] != "0"),
            bool(ctx["title"] and ctx["title"] not in ("-", "0")),
            bool(
                ctx["online_hours"] and ctx["online_hours"] not in ("-", "0 小时", "0")
            ),
            bool(ctx["register_date"] and ctx["register_date"] not in ("-", "0")),
            bool(ctx["last_login_date"] and ctx["last_login_date"] not in ("-", "0")),
        )
    )
    height = _CARD_BASE_HEIGHT + _CARD_VERTICAL_GUTTER
    if has_signature:
        height += _CARD_SIGNATURE_HEIGHT
    if stat_count:
        height += stat_count * _CARD_STATS_ITEM_HEIGHT + _CARD_STATS_DIVIDER_HEIGHT
    height += info_count * _CARD_INFO_ROW_HEIGHT
    return height + _CARD_CLIP_HEIGHT_GUARD


async def render_user_card(
    profile: UserProfile,
    *,
    avatar_bytes: bytes | None = None,
    season: str = "summer",
) -> bytes:
    """渲染用户资料卡片，返回 PNG 字节串。``season`` 取值 spring/summer/fall/winter。"""
    avatar_data = _to_data_uri(avatar_bytes) if avatar_bytes else None
    logo_data = _load_logo_data_uri()

    ctx = {
        "season": season,
        "avatar_data": avatar_data,
        "logo_data": logo_data,
        "username": profile.username or "",
        "uid": profile.uid or "",
        "signature": (profile.signature or "")[:40] or "",
        "hp": str(profile.hp) if profile.hp else "",
        "sp_coin": profile.sp_coin or "",
        "soul": str(profile.soul) if profile.soul else "",
        "essence": str(profile.essence) if profile.essence else "",
        "posts": str(profile.posts) if profile.posts else "",
        "lp": str(profile.lp) if profile.lp else "",
        "title": profile.title or "",
        "online_hours": profile.online_hours or "",
        "register_date": profile.register_date or "",
        "last_login_date": profile.last_login_date or "",
    }

    tmpl = _jinja_env.get_template("profile_card.html")
    html_str = tmpl.render(**ctx)

    result = await html_renderer.render_custom_template(
        html_str,
        {},
        return_url=False,
        options={
            "full_page": False,
            "type": "png",
            "clip": {
                "x": 0,
                "y": 0,
                "width": _CARD_CLIP_WIDTH,
                "height": _profile_card_clip_height(ctx),
            },
        },
    )

    if isinstance(result, bytes):
        return result
    if isinstance(result, str):
        return Path(result).read_bytes()
    raise RuntimeError(f"t2i 返回了非预期类型：{type(result)}")
