"""用户卡片渲染测试。

不做 pixel-perfect 校验，只确认调用不抛错并产出 PNG。
"""

from __future__ import annotations

from src.core.user_card_render import render_user_card
from src.southplus.api import UserProfile


def _sample_profile() -> UserProfile:
    return UserProfile(
        username="flanchan",
        uid="2030219",
        signature="您还没有设置个性签名",
        avatar_url="https://invalid.south-plus.example/avatar.jpg",
        title="Lv.0",
        essence=3,
        posts=128,
        hp=50,
        soul=20,
        sp_coin="14 G",
        lp=7,
        online_hours="10 小时",
        register_date="2023-04-12",
        last_login_date="2026-06-01",
    )


def test_render_returns_valid_png() -> None:
    png = render_user_card(_sample_profile())
    assert isinstance(png, bytes)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 1000


def test_render_with_provided_avatar_bytes() -> None:
    # 一张 1x1 透明 PNG，验证 avatar_bytes 分支不抛错。
    tiny_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )
    png = render_user_card(_sample_profile(), avatar_bytes=tiny_png)
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_render_with_empty_profile_falls_back() -> None:
    # 全部字段为默认值（空串 / 0），渲染不应崩。
    png = render_user_card(UserProfile())
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000
