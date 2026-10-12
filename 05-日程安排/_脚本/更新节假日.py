#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新 `05-日程安排/00-配置/节假日.json` 里的法定节假日表。

数据源：[NateScarlet/holiday-cn](https://github.com/NateScarlet/holiday-cn) —— 跟着国务院办公厅
通知走，逐年版（`2026.json` 里是 `{name, date, isOffDay}` 的列表），社区 PR 维护，比手抄可靠。

为什么走 jsdelivr 镜像：`raw.githubusercontent.com` 在国内常常连不上，`cdn.jsdelivr.net`
是同一份文件的 CDN 镜像（都能用，前一个挂了自动试下一个）。

用法：
    ./更新节假日.bat                    # 刷新配置里 `更新.年份` 列出的年份（默认今年+明年）
    ./更新节假日.bat 2026 2027          # 指定年份
    ./更新节假日.bat --文件 放假.json    # 用本地文件（离线；支持 holiday-cn / timor 两种格式）
    ./更新节假日.bat --dry-run          # 只看会写成什么，不落盘

只写 `放假` / `调休上班` / `更新` 三个键 —— **`假期学习` 和你的手写备注一律保留**。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import 节假日 as H  # noqa: E402

MIRRORS = [
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://testingcf.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
]
UA = {"User-Agent": "obsidian-schedule-vault/1.0 (+holiday sync)"}


def _force_utf8_io() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            pass


_force_utf8_io()


def fetch(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def fetch_year(year: int) -> tuple[dict, str]:
    """按镜像顺序试，返回 (原始 json, 命中的 url)。"""
    last = None
    for tpl in MIRRORS:
        url = tpl.format(year=year)
        try:
            return fetch(url), url
        except Exception as exc:                               # noqa: BLE001
            last = f"{url} → {exc}"
    raise RuntimeError(f"{year} 年的节假日拉取失败；最后一个错误：{last}")


def parse_holiday_cn(raw: dict | list) -> tuple[dict[str, str], dict[str, str]]:
    """holiday-cn 格式：{"days": [{"name":…, "date":"2026-10-01", "isOffDay": true}, …]}"""
    days = raw.get("days") if isinstance(raw, dict) else raw
    off, work = {}, {}
    for d in days or []:
        date, name = str(d.get("date") or "")[:10], str(d.get("name") or "假期")
        if len(date) != 10:
            continue
        if d.get("isOffDay") is True:
            off[date] = name
        elif d.get("isOffDay") is False:
            work[date] = name
    return off, work


def parse_timor(raw: dict) -> tuple[dict[str, str], dict[str, str]]:
    """timor.tech 格式：{"holiday": {"01-01": {"holiday": true, "date": "2026-01-01", …}}}"""
    off, work = {}, {}
    for item in (raw.get("holiday") or {}).values():
        date = str(item.get("date") or "")[:10]
        if len(date) != 10:
            continue
        name = str(item.get("name") or "假期")
        (off if item.get("holiday") else work)[date] = name
    return off, work


def parse_any(raw: dict | list) -> tuple[dict[str, str], dict[str, str]]:
    if isinstance(raw, list):
        return parse_holiday_cn(raw)
    if "days" in raw:
        return parse_holiday_cn(raw)
    if "holiday" in raw:
        return parse_timor(raw)
    raise ValueError("认不出这份数据的格式（要 holiday-cn 的 days[]，或 timor 的 holiday{}）")


def main() -> int:
    ap = argparse.ArgumentParser(description="刷新法定节假日表 → 00-配置/节假日.json")
    ap.add_argument("年份", nargs="*", type=int, help="要刷新的年份（默认：去年/今年/明年）")
    ap.add_argument("--文件", action="append", default=[], help="本地 json（可多次；离线用）")
    ap.add_argument("--dry-run", action="store_true", help="只看结果，不写文件")
    args = ap.parse_args()

    this_year = datetime.now().year
    years = args.年份 or [this_year, this_year + 1]

    all_off: dict[str, str] = {}
    all_work: dict[str, str] = {}
    sources: list[str] = []

    for path_str in args.文件:
        p = Path(path_str)
        raw = json.loads(p.read_text(encoding="utf-8"))
        off, work = parse_any(raw)
        all_off.update(off)
        all_work.update(work)
        sources.append(f"本地 {p.name}")
        print(f"📄 {p.name}：放假 {len(off)} 天｜调休上班 {len(work)} 天")

    for y in years:
        if args.文件 and not args.年份:
            break
        try:
            raw, url = fetch_year(y)
        except Exception as exc:                               # noqa: BLE001
            print(f"⚠️  {y} 年拉取失败：{exc}")
            continue
        off, work = parse_any(raw)
        all_off.update(off)
        all_work.update(work)
        sources.append(url)
        state = f"放假 {len(off)} 天｜调休上班 {len(work)} 天" if off else "⚠️ 还没公布（表是空的）"
        print(f"🌐 {y} 年：{state}")

    if not all_off and not all_work:
        print("❌ 没拿到任何数据，配置未改动。")
        return 1

    covered = sorted({d[:4] for d in all_off} | {d[:4] for d in all_work})
    cfg = H.merge_into_config(all_off, all_work, [int(y) for y in covered], sources[0] if sources else "")

    print()
    print(f"🎌 放假 {len(cfg['放假'])} 天｜🔁 调休上班 {len(cfg['调休上班'])} 天（覆盖 {', '.join(covered)}）")
    for d in sorted(cfg["放假"]):
        print(f"   🎌 {d} {cfg['放假'][d]}")
    for d in sorted(cfg["调休上班"]):
        print(f"   🔁 {d} 调休上班（{cfg['调休上班'][d]}）")

    if args.dry_run:
        print("\n（--dry-run：没写文件）")
        return 0

    H.CONFIG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n✅ 已写入 {H.CONFIG.relative_to(H.VAULT)}（`假期学习` 等人工键原样保留）")
    print("   接着跑： `./打卡.bat <周号>`  +  `./同步日程.bat`  让打卡页和日历跟上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
