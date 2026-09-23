#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今天要看什么：周表 + 连续打卡 + 里程碑倒计时（**跨平台唯一实现**）。

Linux 用 `today.bat`（薄壳）、Windows 用 `today.bat`（薄壳），逻辑都在这一个文件里。

用法：
    python today.py            # 看今天
    python today.py 周三        # 看某一天
    python today.py done       # 打卡（写 _脚本/.打卡.log）
    python today.py done 周三   # 打卡并看那一天
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
TSV = SCRIPT_DIR / "周表.tsv"
LOG = SCRIPT_DIR / ".打卡.log"
PLAN = VAULT / "05-日程安排/00-配置/规划配置.json"
RULES = VAULT / "05-日程安排/00-配置/底线规则.json"
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

try:                                    # Windows 控制台默认不是 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                       # noqa: BLE001
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                   # noqa: BLE001
        return {}


def read_row(day: str) -> list[str] | None:
    if not TSV.exists():
        return None
    for line in TSV.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if cols and cols[0].strip() == day:
            return (cols + [""] * 5)[:5]
    return None


def checkin_done(day: date) -> None:
    LOG.touch()
    text = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
    if f"{day:%Y-%m-%d}" in text.split():
        print(f"今天已打卡（{day:%Y-%m-%d}）")
    else:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{day:%Y-%m-%d}\n")
        print(f"✅ 打卡 {day:%Y-%m-%d}")


def streak(today: date) -> tuple[int, int]:
    if not LOG.exists():
        return 0, 0
    done = set(LOG.read_text(encoding="utf-8").split())
    n, d = 0, today
    while f"{d:%Y-%m-%d}" in done:
        n += 1
        d -= timedelta(days=1)
    return n, len(done)


def bottom_line(rules: dict) -> str:
    if rules.get("打卡页说明"):
        return rules["打卡页说明"]
    items, seen = [], set()
    for rule in (rules.get("触发") or []) + (rules.get("课程底线") or []):
        for it in rule.get("项目") or []:
            if it not in seen:
                seen.add(it); items.append(it)
    for rule in rules.get("每周固定") or []:
        it = rule.get("项目")
        if it and it not in seen:
            seen.add(it); items.append(it)
    return ("零意志力底线：" + " ｜ ".join(items)) if items else ""


def main() -> int:
    args = sys.argv[1:]
    if args and args[0].lower() == "done":
        checkin_done(date.today())
        args = args[1:]
    day = args[0] if args else WEEKDAYS[date.today().weekday()]

    row = read_row(day)
    if row is None:
        print(f"找不到 {day}（检查 {TSV.name} 里是否有这一行）")
        return 1
    _, morning, afternoon, evening, phone = row

    print("=" * 44)
    print(f"  {datetime.now():%Y-%m-%d %A}   →   {day}")
    print("=" * 44)
    print()
    print(f"【上午】     {morning}")
    if afternoon and afternoon.strip() != "—":
        print(f"【下午】     {afternoon}")
    print(f"【晚上】     {evening}")
    print(f"【放下手机】 {phone}")
    print()

    n, total = streak(date.today())
    if LOG.exists():
        print(f"🔥 连续 {n} 天　累计 {total} 天")
        if n == 0:
            print("   （今天还没打卡——底线项见 00-配置/底线规则.json，勾完就算数）")
    else:
        print("🔥 还没开始。今天把底线项做完，就跑 today.bat done / today.bat done")
    print()

    today = date.today()
    for m in load_json(PLAN).get("里程碑") or []:
        try:
            target = date.fromisoformat(m["日期"])
        except Exception:               # noqa: BLE001
            continue
        print(f"  {m.get('名称', '?'):<16}{ (target - today).days:>6} 天")
    print()

    line = bottom_line(load_json(RULES))
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())