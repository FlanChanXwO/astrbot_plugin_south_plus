"""根据 ``UserProfile`` 渲染一张 PNG 用户资料卡片。

设计目标：

* 同步函数（Pillow 是同步库），调用方决定要不要 ``run_in_executor``。
* 字体回落链：``assets/font.ttc`` (本仓库可选) -> macOS PingFang/STHeiti ->
  Arial Unicode -> ``PIL.ImageFont.load_default()``（中文可能渲染成 □）。
* 头像加载策略：``avatar_bytes`` -> 网络拉 ``profile.avatar_url`` -> 占位
  （纯色圆 + 用户名首字母）。
* 字段排列参考用户提供的 profile 截图：左侧大头像 + 右侧两列字段网格。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..southplus.api import UserProfile

# --- 颜色与尺寸常量 ----------------------------------------------------------

_CANVAS_W, _CANVAS_H = 920, 480
_PADDING = 32
_AVATAR_BOX = 260  # 圆形头像直径
_LOGO_BOX = 64

_COLOR_BG = (255, 255, 255)
_COLOR_BORDER = (220, 226, 230)
_COLOR_USERNAME = (37, 99, 235)  # #2563eb
_COLOR_UID_GRAY = (130, 138, 150)
_COLOR_LABEL = (130, 138, 150)
_COLOR_VALUE = (24, 24, 27)
_COLOR_SIGNATURE = (90, 90, 100)
_COLOR_AVATAR_FALLBACK_BG = (200, 220, 255)
_COLOR_AVATAR_FALLBACK_FG = (37, 99, 235)
_COLOR_CARD_SHADOW = (200, 207, 215)

# 字体候选列表，按优先级 try。Path 是绝对路径，避免 cwd 漂移。
_FONT_CANDIDATES: tuple[str, ...] = (
    # 项目自带（仓库放进来时会用到，缺失则跳过）。
    "assets/font.ttc",
    # macOS 系统字体。PingFang 是首选中文字体，但在新版 macOS 上可能
    # 不在公开路径里（被打成 .ttc 移到 AssetsV2）；逐个 try。
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)


@dataclass(slots=True)
class _FontSet:
    title: ImageFont.ImageFont
    username: ImageFont.ImageFont
    uid: ImageFont.ImageFont
    label: ImageFont.ImageFont
    value: ImageFont.ImageFont
    small: ImageFont.ImageFont
    avatar_letter: ImageFont.ImageFont


def render_user_card(
    profile: UserProfile,
    *,
    avatar_bytes: bytes | None = None,
    logo_path: Path | None = None,
) -> bytes:
    """渲染用户资料卡片，返回 PNG 字节串。

    渲染始终成功——网络/字体/头像任何一步失败都会回落到占位实现。
    """

    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), _COLOR_BG)
    draw = ImageDraw.Draw(canvas)

    # 外框：圆角矩形描边。
    draw.rounded_rectangle(
        (4, 4, _CANVAS_W - 4, _CANVAS_H - 4),
        radius=18,
        outline=_COLOR_BORDER,
        width=2,
    )

    fonts = _load_fonts()

    avatar_img = _load_avatar(profile, avatar_bytes)
    avatar_x = _PADDING
    avatar_y = (_CANVAS_H - _AVATAR_BOX) // 2
    _paste_circular(canvas, avatar_img, (avatar_x, avatar_y), _AVATAR_BOX)

    # 右侧布局起点。
    right_x = avatar_x + _AVATAR_BOX + _PADDING
    cursor_y = _PADDING

    # 用户名 + UID。
    username_text = profile.username or "(未知用户)"
    draw.text(
        (right_x, cursor_y),
        username_text,
        fill=_COLOR_USERNAME,
        font=fonts.username,
    )
    username_w = _text_width(draw, username_text, fonts.username)
    uid_text = f"  (数字ID: {profile.uid or '-'})"
    draw.text(
        (right_x + username_w, cursor_y + 8),
        uid_text,
        fill=_COLOR_UID_GRAY,
        font=fonts.uid,
    )
    cursor_y += 44

    # 个性签名。
    signature = profile.signature or "您还没有设置个性签名"
    draw.text(
        (right_x, cursor_y),
        _truncate(signature, 38),
        fill=_COLOR_SIGNATURE,
        font=fonts.small,
    )
    cursor_y += 36

    # 字段网格：两列。
    col_left: list[tuple[str, str]] = [
        ("精华", str(profile.essence)),
        ("发帖", str(profile.posts)),
        ("HP", str(profile.hp)),
        ("魄", str(profile.soul)),
        ("SP币", profile.sp_coin or "-"),
        ("LP", str(profile.lp)),
    ]
    col_right: list[tuple[str, str]] = [
        ("会员头衔", profile.title or "-"),
        ("在线时间", profile.online_hours or "-"),
        ("注册时间", profile.register_date or "-"),
        ("最后登录", profile.last_login_date or "-"),
    ]

    row_h = 36
    col1_x = right_x
    col2_x = right_x + 240
    label_value_gap = 64

    grid_top = cursor_y
    for i, (label, value) in enumerate(col_left):
        y = grid_top + i * row_h
        draw.text((col1_x, y), label, fill=_COLOR_LABEL, font=fonts.label)
        draw.text(
            (col1_x + label_value_gap, y),
            _truncate(value, 16),
            fill=_COLOR_VALUE,
            font=fonts.value,
        )
    for i, (label, value) in enumerate(col_right):
        y = grid_top + i * row_h
        draw.text((col2_x, y), label, fill=_COLOR_LABEL, font=fonts.label)
        draw.text(
            (col2_x + label_value_gap + 12, y),
            _truncate(value, 16),
            fill=_COLOR_VALUE,
            font=fonts.value,
        )

    _paste_logo(canvas, logo_path)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --- 字体 -------------------------------------------------------------------


def _load_fonts() -> _FontSet:
    font_path = _find_font()
    if font_path is None:
        default = ImageFont.load_default()
        # PIL 默认字体不支持中文 -> 中文会渲染成 □。这是预期回落。
        return _FontSet(
            title=default,
            username=default,
            uid=default,
            label=default,
            value=default,
            small=default,
            avatar_letter=default,
        )
    try:
        return _FontSet(
            title=ImageFont.truetype(font_path, 28),
            username=ImageFont.truetype(font_path, 30),
            uid=ImageFont.truetype(font_path, 18),
            label=ImageFont.truetype(font_path, 18),
            value=ImageFont.truetype(font_path, 20),
            small=ImageFont.truetype(font_path, 18),
            avatar_letter=ImageFont.truetype(font_path, 96),
        )
    except OSError:
        default = ImageFont.load_default()
        return _FontSet(
            title=default,
            username=default,
            uid=default,
            label=default,
            value=default,
            small=default,
            avatar_letter=default,
        )


def _find_font() -> str | None:
    plugin_root = Path(__file__).resolve().parents[2]
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if not path.is_absolute():
            path = plugin_root / candidate
        if path.exists() and path.is_file():
            return str(path)
    return None


# --- 头像 -------------------------------------------------------------------


def _load_avatar(profile: UserProfile, avatar_bytes: bytes | None) -> Image.Image:
    if avatar_bytes:
        try:
            return Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        except Exception:
            pass
    if profile.avatar_url:
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(profile.avatar_url)
                if response.status_code == 200 and response.content:
                    return Image.open(io.BytesIO(response.content)).convert("RGBA")
        except Exception:
            pass
    return _placeholder_avatar(profile.username or "?")


def _placeholder_avatar(text: str) -> Image.Image:
    img = Image.new("RGBA", (_AVATAR_BOX, _AVATAR_BOX), _COLOR_AVATAR_FALLBACK_BG)
    draw = ImageDraw.Draw(img)
    letter = (text[:1] or "?").upper()
    fonts = _load_fonts()
    try:
        bbox = draw.textbbox((0, 0), letter, font=fonts.avatar_letter)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        w, h = (40, 60)
    draw.text(
        ((_AVATAR_BOX - w) // 2, (_AVATAR_BOX - h) // 2 - 8),
        letter,
        fill=_COLOR_AVATAR_FALLBACK_FG,
        font=fonts.avatar_letter,
    )
    return img


def _paste_circular(
    canvas: Image.Image,
    src: Image.Image,
    pos: tuple[int, int],
    box: int,
) -> None:
    src = src.convert("RGBA")
    # 等比缩放裁中。
    src_w, src_h = src.size
    scale = max(box / src_w, box / src_h)
    new_w, new_h = (int(src_w * scale), int(src_h * scale))
    src = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - box) // 2
    top = (new_h - box) // 2
    src = src.crop((left, top, left + box, top + box))

    mask = Image.new("L", (box, box), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, box, box), fill=255)

    canvas.paste(src, pos, mask)

    # 头像描边。
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(
        (pos[0], pos[1], pos[0] + box, pos[1] + box),
        outline=_COLOR_CARD_SHADOW,
        width=2,
    )


def _paste_logo(canvas: Image.Image, logo_path: Path | None) -> None:
    if logo_path is None:
        plugin_root = Path(__file__).resolve().parents[2]
        candidate = plugin_root / "assets" / "logo.png"
        if candidate.exists():
            logo_path = candidate
    if logo_path is None or not logo_path.exists():
        return
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return
    logo.thumbnail((_LOGO_BOX, _LOGO_BOX), Image.LANCZOS)
    canvas.paste(
        logo,
        (_CANVAS_W - _PADDING - logo.size[0], _CANVAS_H - _PADDING - logo.size[1]),
        logo,
    )


# --- 文本工具 ---------------------------------------------------------------


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 12


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"
