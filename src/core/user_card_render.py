"""根据 ``UserProfile`` 渲染一张浅色卡片风格 PNG 用户资料卡片。

设计：
* 浅色季节渐变背景 + 白色圆角卡片居中
* 上方居中头像 / 用户名 / UID / 个性签名
* 中部 HP/SP币/魄 横向统计条（左标签右数值，垂直堆叠）
* 下方单列字段网格，空值自动隐藏
* 右上角 logo 水印（低调半透明，无底衬）
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..southplus.api import UserProfile

# --- 尺寸常量 ----------------------------------------------------------------

_CANVAS_W, _CANVAS_H = 400, 670
_CARD_X, _CARD_Y = 20, 40
_CARD_W, _CARD_H = 360, 590
_CARD_RADIUS = 12

_AVATAR_BOX = 100
_LOGO_SIZE = 28

# --- 四季浅色配色 ------------------------------------------------------------

_SEASON_THEMES: dict[str, dict] = {
    "spring": {
        "gradient_top": (254, 240, 245),  # #fef0f5
        "gradient_btm": (245, 255, 240),  # #f5fff0
        "accent": (232, 122, 146),  # 樱花粉
        "accent_dim": (200, 100, 120),
        "text": (31, 41, 55),
        "text_dim": (107, 114, 128),
        "shadow": (232, 122, 146, 30),
    },
    "summer": {
        "gradient_top": (232, 244, 255),  # #e8f4ff
        "gradient_btm": (255, 255, 255),  # #ffffff
        "accent": (74, 158, 255),  # 天蓝
        "accent_dim": (50, 110, 190),
        "text": (31, 41, 55),
        "text_dim": (107, 114, 128),
        "shadow": (74, 158, 255, 30),
    },
    "fall": {
        "gradient_top": (254, 245, 232),  # #fef5e8
        "gradient_btm": (254, 254, 245),  # #fefef5
        "accent": (232, 141, 74),  # 枫橙
        "accent_dim": (180, 105, 50),
        "text": (31, 41, 55),
        "text_dim": (107, 114, 128),
        "shadow": (232, 141, 74, 30),
    },
    "winter": {
        "gradient_top": (238, 245, 250),  # #eef5fa
        "gradient_btm": (255, 255, 255),  # #ffffff
        "accent": (123, 169, 212),  # 冰蓝
        "accent_dim": (85, 120, 155),
        "text": (31, 41, 55),
        "text_dim": (107, 114, 128),
        "shadow": (123, 169, 212, 30),
    },
}

# 属性数值块配色
_STAT_BLOCK_STYLES: dict[str, dict] = {
    "HP": {"bg": (254, 226, 226), "value_color": (220, 38, 38), "icon": "♥"},
    "SP币": {"bg": (254, 243, 199), "value_color": (217, 119, 6), "icon": "●"},
    "魄": {"bg": (243, 232, 255), "value_color": (147, 51, 234), "icon": "◆"},
}

# 字体候选列表
_FONT_CANDIDATES: tuple[str, ...] = (
    "assets/font.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)


@dataclass(slots=True)
class _FontSet:
    username: ImageFont.ImageFont
    uid: ImageFont.ImageFont
    signature: ImageFont.ImageFont
    stat_value: ImageFont.ImageFont
    stat_label: ImageFont.ImageFont
    text: ImageFont.ImageFont
    avatar_letter: ImageFont.ImageFont


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def render_user_card(
    profile: UserProfile,
    *,
    avatar_bytes: bytes | None = None,
    logo_path: Path | None = None,
    season: str = "summer",
) -> bytes:
    """渲染用户资料卡片，返回 PNG 字节串。``season`` 取值 spring/summer/fall/winter。"""
    theme = _SEASON_THEMES.get(season, _SEASON_THEMES["summer"])
    fonts = _load_fonts()

    canvas = Image.new("RGBA", (_CANVAS_W, _CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # 1) 浅色季节渐变背景
    _draw_background(draw, theme)

    # 2) 白色圆角卡片（带阴影效果）
    card_rect = (_CARD_X, _CARD_Y, _CARD_X + _CARD_W, _CARD_Y + _CARD_H)
    draw.rounded_rectangle(card_rect, radius=_CARD_RADIUS, fill=(255, 255, 255))
    # 卡片描边
    a = theme["accent"]
    draw.rounded_rectangle(
        card_rect, radius=_CARD_RADIUS, outline=(a[0], a[1], a[2], 50), width=1
    )

    cx = _CARD_X + _CARD_W // 2

    # 3) 右上角 logo
    _draw_logo(canvas, logo_path, card_rect, theme)

    # 4) 居中头像
    avatar_img = _load_avatar(profile, avatar_bytes)
    av_y = _CARD_Y + 32
    _paste_avatar(canvas, draw, avatar_img, cx, av_y, theme)

    # 5) 居中用户名 / UID / 签名
    header_top = av_y + _AVATAR_BOX + 14
    cy = _draw_centered_header(draw, profile, cx, header_top, theme, fonts)

    # 6) 居中属性数值块
    block_y = cy + 20
    grid_y = _draw_stat_blocks(draw, profile, cx, block_y, fonts)

    # 7) 文本网格
    grid_y = grid_y + 14
    _draw_text_grid(draw, profile, cx, grid_y, theme, fonts)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 背景
# ---------------------------------------------------------------------------


def _draw_background(draw: ImageDraw.ImageDraw, theme: dict) -> None:
    top = theme["gradient_top"]
    btm = theme["gradient_btm"]
    for y in range(_CANVAS_H):
        r = y / _CANVAS_H
        draw.line(
            (0, y, _CANVAS_W, y),
            fill=(
                int(top[0] + (btm[0] - top[0]) * r),
                int(top[1] + (btm[1] - top[1]) * r),
                int(top[2] + (btm[2] - top[2]) * r),
            ),
        )


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------


def _draw_logo(
    canvas: Image.Image,
    logo_path: Path | None,
    card_rect: tuple[int, int, int, int],
    theme: dict,
) -> None:
    logo_img = _load_logo_image(logo_path)
    if logo_img is None:
        return
    lx = card_rect[2] - 16 - logo_img.size[0]
    ly = card_rect[1] + 14
    # 降低不透明度，作为低调水印
    logo_img = _fade_image(logo_img, 40)
    canvas.paste(logo_img, (lx, ly), logo_img)


def _load_logo_image(logo_path: Path | None) -> Image.Image | None:
    if logo_path is None:
        plugin_root = Path(__file__).resolve().parents[2]
        candidate = plugin_root / "resources" / "logo-spring-south.png"
        if candidate.exists():
            logo_path = candidate
    if logo_path is None or not logo_path.exists():
        return None
    try:
        logo = Image.open(logo_path).convert("RGBA")
        # 南+ logo 原图白底不透明，去除白色像素使其可在任何底色上叠加。
        data = logo.getdata()
        new_data = []
        for r, g, b, a in data:
            if r > 240 and g > 240 and b > 240:
                new_data.append((r, g, b, 0))
            else:
                new_data.append((r, g, b, a))
        logo.putdata(new_data)
        logo.thumbnail((_LOGO_SIZE, _LOGO_SIZE), Image.LANCZOS)
        return logo
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 头像
# ---------------------------------------------------------------------------


def _load_avatar(profile: UserProfile, avatar_bytes: bytes | None) -> Image.Image:
    if avatar_bytes:
        try:
            return Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        except Exception:
            pass
    if profile.avatar_url:
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(profile.avatar_url)
                if resp.status_code == 200 and resp.content:
                    return Image.open(io.BytesIO(resp.content)).convert("RGBA")
        except Exception:
            pass
    return _placeholder_avatar(profile.username or "?")


def _placeholder_avatar(text: str) -> Image.Image:
    box = _AVATAR_BOX
    img = Image.new("RGBA", (box, box), (200, 220, 255, 255))
    draw = ImageDraw.Draw(img)
    letter = (text[:1] or "?").upper()
    fonts = _load_fonts()
    try:
        bbox = draw.textbbox((0, 0), letter, font=fonts.avatar_letter)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        w, h = 40, 60
    draw.text(
        ((box - w) // 2, (box - h) // 2 - 6),
        letter,
        fill=(37, 99, 235, 255),
        font=fonts.avatar_letter,
    )
    return img


def _paste_avatar(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    src: Image.Image,
    cx: int,
    y: int,
    theme: dict,
) -> None:
    box = _AVATAR_BOX
    x = cx - box // 2

    src = src.convert("RGBA")
    src_w, src_h = src.size
    scale = max(box / src_w, box / src_h)
    nw, nh = int(src_w * scale), int(src_h * scale)
    src = src.resize((nw, nh), Image.LANCZOS)
    left = (nw - box) // 2
    top_pad = (nh - box) // 2
    src = src.crop((left, top_pad, left + box, top_pad + box))

    mask = Image.new("L", (box, box), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, box, box), fill=255)
    canvas.paste(src, (x, y), mask)

    a = theme["accent"]
    # 季节色描边
    draw.ellipse((x, y, x + box, y + box), outline=(a[0], a[1], a[2], 180), width=3)
    # 外发光
    draw.ellipse(
        (x - 2, y - 2, x + box + 2, y + box + 2),
        outline=(a[0], a[1], a[2], 60),
        width=4,
    )


# ---------------------------------------------------------------------------
# 居中用户名 / UID / 签名
# ---------------------------------------------------------------------------


def _draw_centered_header(
    draw: ImageDraw.ImageDraw,
    profile: UserProfile,
    cx: int,
    y: int,
    theme: dict,
    fonts: _FontSet,
) -> int:
    text_color = theme["text"]
    dim = theme["text_dim"]
    ac = theme["accent"]

    username = profile.username or "(未知用户)"
    _draw_centered_text(draw, username, cx, y, fonts.username, text_color)
    y += 38

    uid = f"数字ID: {profile.uid or '-'}"
    _draw_centered_text(draw, uid, cx, y, fonts.uid, dim)
    y += 26

    sig = profile.signature
    if sig:
        _draw_centered_text(draw, _truncate(sig, 40), cx, y, fonts.signature, dim)
        draw.line(
            (cx - 80, y + 20, cx + 80, y + 20), fill=(ac[0], ac[1], ac[2], 30), width=1
        )
        y += 34
    else:
        draw.line(
            (cx - 80, y - 2, cx + 80, y - 2), fill=(ac[0], ac[1], ac[2], 30), width=1
        )

    return y


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    y: int,
    font: ImageFont.ImageFont,
    color: tuple[int, ...],
) -> None:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(text) * 14
    draw.text((cx - tw // 2, y), text, fill=color, font=font)


# ---------------------------------------------------------------------------
# 属性数值块
# ---------------------------------------------------------------------------


def _draw_stat_blocks(
    draw: ImageDraw.ImageDraw,
    profile: UserProfile,
    cx: int,
    y: int,
    fonts: _FontSet,
) -> int:
    """绘制垂直堆叠的横向统计条，返回后续内容的 y 坐标。"""
    bar_w = _CARD_W - 40  # 320
    bar_h = 32
    gap = 6
    sx = cx - bar_w // 2

    items: list[tuple[str, int | str]] = [
        ("HP", profile.hp),
        ("SP币", profile.sp_coin or "-"),
        ("魄", profile.soul),
    ]
    visible = [(label, str(v)) for label, v in items if _is_empty_stat(v)]

    cur_y = y
    for label, value in visible:
        s = _STAT_BLOCK_STYLES.get(label, {})
        bg = s.get("bg", (240, 240, 240))
        val_color = s.get("value_color", (60, 60, 60))

        draw.rounded_rectangle(
            (sx, cur_y, sx + bar_w, cur_y + bar_h), radius=8, fill=bg
        )

        draw.text(
            (sx + 12, cur_y + 8), label, fill=(120, 120, 120), font=fonts.stat_label
        )
        # 数值右对齐
        try:
            vbbox = draw.textbbox((0, 0), value, font=fonts.stat_value)
            vw = vbbox[2] - vbbox[0]
        except Exception:
            vw = len(value) * 14
        draw.text(
            (sx + bar_w - 12 - vw, cur_y + 5),
            value,
            fill=val_color,
            font=fonts.stat_value,
        )

        cur_y += bar_h + gap

    return cur_y - gap if visible else y


# ---------------------------------------------------------------------------
# 文本字段网格
# ---------------------------------------------------------------------------


def _draw_text_grid(
    draw: ImageDraw.ImageDraw,
    profile: UserProfile,
    cx: int,
    y: int,
    theme: dict,
    fonts: _FontSet,
) -> None:
    dim = theme["text_dim"]
    ac = theme["accent"]

    rows: list[tuple[str, str]] = [
        ("精华", str(profile.essence)),
        ("发帖", str(profile.posts)),
        ("LP", str(profile.lp)),
        ("会员头衔", profile.title or "-"),
        ("在线时间", profile.online_hours or "-"),
        ("注册时间", profile.register_date or "-"),
        ("最后登录", profile.last_login_date or "-"),
    ]

    def _empty(v: str) -> bool:
        return v in ("", "0", "-", "None", "0 小时")

    # 分隔线
    draw.line((cx - 90, y - 6, cx + 90, y - 6), fill=(ac[0], ac[1], ac[2], 30), width=1)

    col_lx = cx - 90
    row_h = 26
    bar_w = _CARD_W - 40  # 320

    ry = y
    for label, value in rows:
        if _empty(value):
            continue
        # 标签左对齐
        draw.text((col_lx, ry), label, fill=dim, font=fonts.text)
        # 数值右对齐
        try:
            vbbox = draw.textbbox((0, 0), value, font=fonts.text)
            vw = vbbox[2] - vbbox[0]
        except Exception:
            vw = len(value) * 12
        draw.text((col_lx + bar_w - vw, ry), value, fill=dim, font=fonts.text)
        ry += row_h


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------


def _load_fonts() -> _FontSet:
    fp = _find_font()
    if fp is None:
        d = ImageFont.load_default()
        return _FontSet(
            username=d,
            uid=d,
            signature=d,
            stat_value=d,
            stat_label=d,
            text=d,
            avatar_letter=d,
        )
    try:
        return _FontSet(
            username=ImageFont.truetype(fp, 28),
            uid=ImageFont.truetype(fp, 16),
            signature=ImageFont.truetype(fp, 15),
            stat_value=ImageFont.truetype(fp, 22),
            stat_label=ImageFont.truetype(fp, 13),
            text=ImageFont.truetype(fp, 15),
            avatar_letter=ImageFont.truetype(fp, 80),
        )
    except OSError:
        d = ImageFont.load_default()
        return _FontSet(
            username=d,
            uid=d,
            signature=d,
            stat_value=d,
            stat_label=d,
            text=d,
            avatar_letter=d,
        )


def _find_font() -> str | None:
    root = Path(__file__).resolve().parents[2]
    for c in _FONT_CANDIDATES:
        p = Path(c)
        if not p.is_absolute():
            p = root / c
        if p.exists() and p.is_file():
            return str(p)
    return None


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _is_empty_stat(v: int | str | None) -> bool:
    """统计值是否应视为空（隐藏），兼容 int 和 str 类型。"""
    if v is None:
        return False
    if isinstance(v, int):
        return v != 0
    return v not in ("", "-", "0", "None")


def _fade_image(img: Image.Image, alpha: int) -> Image.Image:
    """将图像所有像素的 alpha 通道乘以给定比例（0-255）。"""
    img = img.copy()
    data = img.getdata()
    new_data = []
    for r, g, b, a in data:
        new_data.append((r, g, b, (a * alpha) // 255))
    img.putdata(new_data)
    return img


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"
