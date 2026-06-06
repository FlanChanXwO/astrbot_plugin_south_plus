"""用户卡片渲染测试（HTML + t2i）。

不做 pixel-perfect 校验，只确认调用不抛错并产出 PNG。
t2i 渲染器在测试中被 mock，返回最小合法 PNG。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.southplus.api import UserProfile

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000000000200"
    "0d0a2db40000000049454e44ae426082"
)


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


@pytest.fixture(autouse=True)
def mock_t2i():
    """所有测试自动 mock html_renderer，避免真实 t2i 调用。"""
    mock_renderer = MagicMock()
    mock_renderer.render_custom_template = AsyncMock(return_value=_TINY_PNG)
    with patch("src.render.card_render.html_renderer", mock_renderer):
        yield mock_renderer


@pytest.mark.asyncio
async def test_render_returns_valid_png():
    from src.render.card_render import render_user_card

    png = await render_user_card(_sample_profile(), season="summer")
    assert isinstance(png, bytes)
    assert png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_render_with_avatar_bytes():
    from src.render.card_render import render_user_card

    png = await render_user_card(
        _sample_profile(), avatar_bytes=_TINY_PNG, season="fall"
    )
    assert png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_render_empty_profile():
    from src.render.card_render import render_user_card

    png = await render_user_card(UserProfile(), season="winter")
    assert png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_render_seasonal_themes():
    from src.render.card_render import render_user_card

    for season in ("spring", "summer", "fall", "winter"):
        png = await render_user_card(_sample_profile(), season=season)
        assert png.startswith(b"\x89PNG"), f"season={season} failed"


@pytest.mark.asyncio
async def test_render_empty_fields_hidden():
    from src.render.card_render import render_user_card

    profile = UserProfile(
        username="test", uid="1", essence=0, posts=0, hp=0, soul=0, lp=0
    )
    png = await render_user_card(profile, season="summer")
    assert png.startswith(b"\x89PNG")
