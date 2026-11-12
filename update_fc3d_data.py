#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
福彩3D 数据更新脚本

从东方财富网 (https://caipiao.eastmoney.com/Result/History/fc3d) 抓取最新开奖数据并增量更新。
与 lottery-predictor-main/update_data.py 风格保持一致：requests 优先，失败不阻断。
"""

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup


DATA_FILE = "fc3d_data.json"
BASE_URL = "https://caipiao.eastmoney.com/Result/History/fc3d"
DEFAULT_PAGES = 10  # 默认抓取最近 10 页（约 500 期）
REQUEST_DELAY = 0.5
CURL_TIMEOUT = 40  # curl 单次请求超时（秒）
CURL_COMMANDS = ("curl.exe", "curl")  # Windows 优先 curl.exe，兼容类 Unix 环境的 curl


def load_existing_data() -> Dict:
    """加载现有数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"metadata": {}, "records": []}


def build_date_range(records: List[Dict]) -> str:
    """统一生成从旧到新的日期范围文本"""
    if not records:
        return ""
    ordered = sorted(records, key=lambda x: x["date"])
    return f"{ordered[0]['date']} 至 {ordered[-1]['date']}"


def save_data(records: List[Dict], source: str = "eastmoney-real", is_real: bool = True) -> None:
    """保存数据，records 按日期倒序"""
    records = sorted(records, key=lambda x: x["date"], reverse=True)
    data = {
        "metadata": {
            "total_records": len(records),
            "date_range": build_date_range(records),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "is_real": is_real,
        },
        "records": records,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_page(html_text: str) -> List[Dict]:
    """解析单页 HTML 表格"""
    records = []
    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.select("table tr")
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.select("td, th")]
        if len(cells) < 5:
            continue
        period = cells[0]
        date_text = cells[1]
        number = cells[3]
        if not re.fullmatch(r"\d{7}", period):
            continue
        if not re.fullmatch(r"\d{3}", number):
            continue
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", date_text)
        if not date_match:
            continue
        date = date_match.group(1)
        digits = [int(c) for c in number]
        records.append({"period": period, "date": date, "digits": digits})
    return records


def fetch_page(page: int, headers: Dict) -> Optional[str]:
    """获取单页 HTML。

    优先使用 requests；若返回空响应（部分站点会按 TLS 指纹拦截 Python 客户端，
    表现为 HTTP 200 但响应体长度为 0），则自动降级到 curl 传输层重试。
    """
    url = BASE_URL if page <= 1 else f"{BASE_URL}?page={page}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200 and resp.content:
            return resp.text
        if resp.status_code == 200:
            print(f"   第 {page} 页 requests 返回空响应，降级 curl 重试")
        else:
            print(f"   第 {page} 页请求返回 {resp.status_code}")
    except Exception as e:
        print(f"   第 {page} 页请求失败: {e}")

    return fetch_page_with_curl(url, page, headers)


def find_curl() -> Optional[str]:
    """定位可用的 curl 可执行文件。"""
    for cmd in CURL_COMMANDS:
        if shutil.which(cmd):
            return cmd
    return None


def fetch_page_with_curl(url: str, page: int, headers: Dict) -> Optional[str]:
    """使用 curl 作为传输层抓取页面（requests 被 TLS 指纹拦截时的降级方案）。

    注意：不使用 --compressed，因为部分 Windows 自带 curl 的 libcurl 不支持该选项。
    """
    curl = find_curl()
    if not curl:
        print(f"   第 {page} 页未找到可用的 curl，跳过")
        return None

    cmd = [
        curl,
        "-s",
        "--max-time",
        str(CURL_TIMEOUT),
        "-A",
        headers.get("User-Agent", ""),
        "-e",
        headers.get("Referer", ""),
        url,
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=CURL_TIMEOUT + 20)
    except Exception as e:
        print(f"   第 {page} 页 curl 执行异常: {e}")
        return None

    if completed.returncode != 0:
        print(f"   第 {page} 页 curl 返回码 {completed.returncode}")
        return None

    html = completed.stdout.decode("utf-8", errors="replace")
    if not html.strip():
        print(f"   第 {page} 页 curl 返回空响应")
        return None
    return html


def fetch_all_records(max_pages: int = DEFAULT_PAGES) -> List[Dict]:
    """抓取多页数据并合并"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://caipiao.eastmoney.com/",
    }
    records_by_period: Dict[str, Dict] = {}
    print(f"🌐 开始从东方财富网抓取福彩3D数据，最多 {max_pages} 页...")
    for page in range(1, max_pages + 1):
        html = fetch_page(page, headers)
        if html is None:
            break
        page_records = parse_page(html)
        if not page_records:
            print(f"   第 {page} 页未解析到记录，停止抓取")
            break
        for r in page_records:
            records_by_period[r["period"]] = r
        print(f"   第 {page} 页解析 {len(page_records)} 条，累计 {len(records_by_period)} 条")
        if page < max_pages:
            time.sleep(REQUEST_DELAY)
    return list(records_by_period.values())


def merge_records(existing_records: List[Dict], new_records: List[Dict]) -> int:
    """合并数据（增量更新），按 period 去重"""
    existing_periods = {r["period"] for r in existing_records}
    added = 0
    for record in new_records:
        if record["period"] not in existing_periods:
            existing_records.append(record)
            existing_periods.add(record["period"])
            added += 1
    return added


def main():
    parser = __import__("argparse").ArgumentParser(description="福彩3D 数据更新脚本")
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=f"抓取页数，每页约50期，默认 {DEFAULT_PAGES} 页",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="抓取全部历史页（约154页，约7700期）",
    )
    args = parser.parse_args()

    max_pages = 154 if args.all else args.pages

    print("=" * 60)
    print("🔄 福彩3D 数据更新工具")
    print("=" * 60)

    data = load_existing_data()
    existing_records = data.get("records", [])
    print(f"📁 现有数据: {len(existing_records)} 期")

    new_records = fetch_all_records(max_pages)
    if new_records:
        print(f"\n✅ 获取到 {len(new_records)} 条数据")
        added = merge_records(existing_records, new_records)
        print(f"✅ 新增 {added} 条记录")
        print(f"📊 当前共 {len(existing_records)} 条记录")
        save_data(existing_records)
        print(f"\n💾 数据已保存到 {DATA_FILE}")
        print(f"📅 数据范围: {build_date_range(existing_records)}")
    else:
        print("❌ 未能获取新数据")

    print("=" * 60)


if __name__ == "__main__":
    main()
