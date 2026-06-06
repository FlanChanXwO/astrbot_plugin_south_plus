#!/usr/bin/env python3
"""抓取 South Plus 各季节站点 logo 图片到 resources/ 目录。

原理：
1. 请求 ``https://bbs.south-plus.org/index.php``
2. 从内联 JS 解析 #season-logo 的季节图片映射
3. 依次下载各季节图片到 ``resources/``

用法：:

    # 直连（本机可穿透 Cloudflare 时）
    python scripts/fetch-season-logos.py

    # 通过代理
    python scripts/fetch-season-logos.py --proxy http://127.0.0.1:7890

    # 自定义站点和输出目录
    python scripts/fetch-season-logos.py --base-url https://bbs.south-plus.org \
        --output path/to/resources
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx


# 默认值
DEFAULT_BASE_URL = "https://bbs.south-plus.org"
LOGOS_RELPATH = "images/colorImagination"


def parse_logo_map(html: str) -> dict[str, str]:
    """从 index page HTML 中提取 ``logoMap`` 数组，返回 ``{季节名: 文件名}``。"""

    # JS 中的结构：
    #   {name: 'logo-winter5.png', months: [12,1,2]},
    #   {name: 'logo-spring-south.png', months: [3,4,5]},
    #   ...
    entries = re.findall(
        r"\{\s*name:\s*'([^']+)'\s*,\s*months:\s*\[([^\]]+)\]\s*\}",
        html,
    )
    if not entries:
        print("错误：无法在页面中找到季节 logo 映射", file=sys.stderr)
        sys.exit(1)

    season_map: dict[str, str] = {}
    for filename, months_str in entries:
        months = [int(m.strip()) for m in months_str.split(",")]
        # 取第一个月份作为代表（12=冬，3=春，6=夏，9=秋）
        rep_month = months[0]
        if rep_month == 12:
            season = "winter"
        elif rep_month == 3:
            season = "spring"
        elif rep_month == 6:
            season = "summer"
        elif rep_month == 9:
            season = "fall"
        else:
            season = f"month{rep_month}"
        season_map[season] = filename

    return season_map


def fetch_season_logos(
    *,
    base_url: str = DEFAULT_BASE_URL,
    proxy: str | None = None,
    output_dir: str | Path = "resources",
) -> list[Path]:
    """主流程：抓取页面 → 解析映射 → 下载图片。"""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 1. 请求 index page
    client_kw: dict = {}
    if proxy:
        client_kw["proxy"] = proxy

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    with httpx.Client(
        headers={"User-Agent": ua},
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        **client_kw,
    ) as client:
        print(f"获取 {base_url}/ ...")
        resp = client.get(urljoin(base_url, "/index.php"))
        resp.raise_for_status()
        html = resp.text

        # 2. 解析季节映射
        season_map = parse_logo_map(html)
        print(f"找到 {len(season_map)} 个季节 logo：{json.dumps(season_map, indent=2)}")

        # 也检查是否有 isSnowSeason 特殊雪天 logo
        snow_match = re.search(r'isSnowSeason\(\).*?logo\s*=\s*"([^"]+)"', html)
        if snow_match:
            snow_file = snow_match.group(1)
            if snow_file not in season_map.values():
                season_map["snow"] = snow_file
                print(f"额外雪天 logo：{snow_file}")

        # 3. 去重下载
        seen: set[str] = set()
        downloaded: list[Path] = []

        for season, filename in season_map.items():
            if filename in seen:
                print(f"  [{season}] {filename}（已下载，跳过）")
                continue
            seen.add(filename)

            img_url = urljoin(base_url, f"/{LOGOS_RELPATH}/{filename}")
            out_file = output_path / filename

            print(f"  [{season}] 下载 {img_url} ...", end=" ", flush=True)
            img_resp = client.get(img_url)
            if img_resp.status_code != 200:
                print(f"失败（HTTP {img_resp.status_code}）")
                continue

            out_file.write_bytes(img_resp.content)
            print(f"完成（{len(img_resp.content)} bytes）")
            downloaded.append(out_file)

    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 South Plus 各季节站点 logo")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"站点根地址（默认 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="HTTP 代理地址，例如 http://127.0.0.1:7890",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出目录（默认 scripts/../resources）",
    )

    args = parser.parse_args()

    output_dir = args.output
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "resources"

    downloaded = fetch_season_logos(
        base_url=args.base_url,
        proxy=args.proxy,
        output_dir=output_dir,
    )
    print(f"\n完成：下载了 {len(downloaded)} 个 logo 到 {output_dir}")


if __name__ == "__main__":
    main()
