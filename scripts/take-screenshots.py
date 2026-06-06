#!/usr/bin/env python3
"""Playwright 截图 — 登录页面四季样式预览。

用法：:

    python scripts/take-screenshots.py                          # 默认 chromium
    python scripts/take-screenshots.py --browser firefox
    PLAYWRIGHT_BROWSERS_PATH=0 python scripts/take-screenshots.py
"""

from __future__ import annotations

import argparse
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

# 把项目根加到 sys.path，使 src 可导入
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.core.auth_server import CredentialFormServer  # noqa: E402
from src.core.datamodels import AuthServerConfig  # noqa: E402
from src.southplus.api import (  # noqa: E402
    SouthPlusEndpoints,
    SouthPlusLoginApi,
    SouthPlusSession,
)

# 1x1 透明 PNG（用作 mock 验证码）。
_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000005000100"
    "0d0a2db40000000049454e44ae426082"
)

# 四季对应关系：season_name -> (logo_filename, 季节显示名)
SEASONS: list[tuple[str, str, str]] = [
    ("spring", "logo-spring-south.png", "春"),
    ("summer", "logo-s-summer2.png", "夏"),
    ("fall", "logo-fall4.png", "秋"),
    ("winter", "logo-winter5.png", "冬"),
]

OUTPUT_DIR = _PROJECT_ROOT / "tests" / "output"


def _start_mock_sp_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    """启动一个最小 mock 南+ 服务，仅返回验证码图片。"""
    handler_cls = _make_mock_handler()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _make_mock_handler() -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_GET(self) -> None:
            self.send_response(200)
            if "/ck.php" in self.path:
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(_MIN_PNG)
            else:
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html>mock</html>")

        def do_POST(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "message": "mock ok"}')

    return _Handler


def take_screenshots(browser_type: str = "chromium") -> list[Path]:
    """遍历四季，截图保存到 tests/output/。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 启动 mock SouthPlus 服务器
    mock_server, mock_thread = _start_mock_sp_server()
    host, port = mock_server.server_address[:2]
    mock_base = f"http://{host}:{port}"

    endpoints = SouthPlusEndpoints(
        site_base_url=mock_base,
        login_url=f"{mock_base}/login.php",
        captcha_url=f"{mock_base}/ck.php",
        verify_url=f"{mock_base}/index.php",
        cookie_domains=("127.0.0.1",),
        user_agent="screenshot-bot",
    )
    client = SouthPlusLoginApi(SouthPlusSession(endpoints))
    # 静态回调
    on_success = lambda _s, _r, _res: None  # noqa: E731

    captured: list[Path] = []

    with sync_playwright() as pw:
        browser = getattr(pw, browser_type).launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 390, "height": 844},  # iPhone 14 Pro 尺寸
            device_scale_factor=2,
        )

        for season_name, logo_file, season_label in SEASONS:
            print(f"\n[{season_name}] {season_label}...", end=" ", flush=True)

            patch_season = patch(
                "src.core.auth_server._season_name", return_value=season_name
            )
            patch_logo = patch(
                "src.core.auth_server._seasonal_logo", return_value=logo_file
            )
            patch_season.start()
            patch_logo.start()

            page = context.new_page()
            try:
                server = CredentialFormServer(
                    config=AuthServerConfig(
                        listen_host="127.0.0.1",
                        listen_port=0,
                        base_url="",
                        token_ttl_seconds=600,
                    ),
                    client=client,
                    on_login_success=on_success,
                )
                # --- login page ---
                session = server.create_session(
                    user_key="screenshot", unified_msg_origin="umo"
                )
                base = f"http://{server.config.listen_host}:{server.actual_port}"
                url = server.build_url(session.token)
                page.goto(url, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(500)
                out_path = OUTPUT_DIR / f"login-{season_name}.png"
                page.screenshot(path=str(out_path), full_page=True)
                captured.append(out_path)
                print("login ✓", end=" ", flush=True)

                # --- expired page（用假 token 触发） ---
                page.goto(
                    base + "/login/FAKETOKEN", wait_until="networkidle", timeout=15000
                )
                page.wait_for_timeout(300)
                out_path = OUTPUT_DIR / f"expired-{season_name}.png"
                page.screenshot(path=str(out_path), full_page=True)
                captured.append(out_path)
                print("expired ✓", end=" ", flush=True)

                # --- 404 page ---
                page.goto(base + "/garbage", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(300)
                out_path = OUTPUT_DIR / f"404-{season_name}.png"
                page.screenshot(path=str(out_path), full_page=True)
                captured.append(out_path)
                print("404 ✓", end=" ", flush=True)
            except Exception as exc:
                print(f"✗ {exc}")
            finally:
                page.close()
                server.shutdown()
                patch_season.stop()
                patch_logo.stop()

        browser.close()

    mock_server.shutdown()

    return captured


def main() -> None:
    parser = argparse.ArgumentParser(description="South Plus 登录页四季截图")
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=["chromium", "firefox", "webkit"],
        help="Playwright 浏览器引擎（默认 chromium）",
    )
    args = parser.parse_args()

    print(f"输出目录：{OUTPUT_DIR}")
    results = take_screenshots(browser_type=args.browser)
    print(f"\n完成：{len(results)} 张截图:")
    for p in results:
        print(f"  {p}")


if __name__ == "__main__":
    main()
