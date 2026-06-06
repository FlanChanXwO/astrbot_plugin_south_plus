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
        html_str, {}, return_url=False, options={"full_page": True, "type": "png"}
    )

    if isinstance(result, bytes):
        return result
    if isinstance(result, str):
        return Path(result).read_bytes()
    raise RuntimeError(f"t2i 返回了非预期类型：{type(result)}")
