#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假期学习块：把法定节假日每天 **4–6h** 的学习定额，生成可直接贴进周决策的任务行。

背景：平时按 `03-时间预算与周表.md` 的骨架（23h/周）走；**假期没人给你排课，最容易整天滑掉**，
所以这里给一个机械定额 —— 每天 4–6h，写进周决策后就自动进日历（📅 + 时间区间 → 定时事件）。

用法：
    ./假期块.bat 2026-W40        # 输出那一周假期日的任务行（直接复制进周决策 ① 本周任务）
    ./假期块.bat                 # 本周
    ./假期块.bat 2026-W40 --print   # 同上（默认就是打印；这个参数只是写清楚）

定额与分配在 `00-配置/节假日.json` 的 `假期学习`：
    分配 = {西语 2.5, 数学科 2, 外语科 1.5} → 3 块正好 6h（区间上限）
    要压到 4h：删掉『外语科』那块（4.5h），或把『数学科』改 1.5（4h）
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import 节假日 as H  # noqa: E402

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _force_utf8_io() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            pass


_force_utf8_io()


def week_dates(week: str) -> tuple[datetime, datetime]:
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", week.strip())
    if not m:
        sys.exit(f"❌ 周号格式应为 2026-W40，收到：{week}")
    mon = datetime.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return mon, mon + timedelta(days=6)


def week_of(d: datetime) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _h(x: float) -> str:
    return f"{x:g}h"


def blocks_for_day(day: datetime, name: str, cfg: dict) -> list[str]:
    """一天的假期学习块 → 任务行。"""
    alloc = cfg.get("分配") or H.DEFAULT_STUDY["分配"]
    slots = cfg.get("时段") or H.DEFAULT_STUDY["时段"]
    labels = cfg.get("科目名") or H.DEFAULT_STUDY["科目名"]
    lo, hi = cfg.get("每天最少", 4), cfg.get("每天最多", 6)

    lines: list[str] = []
    total = 0.0
    for i, (subj, hours) in enumerate(alloc.items()):
        if i >= len(slots):
            break
        t1, t2 = slots[i][0], slots[i][1]
        total += float(hours)
        lines.append(
            f"- [ ] {labels.get(subj, subj)} {_h(float(hours))} 📅 {day:%Y-%m-%d} {t1} - {t2}"
        )
    warn = ""
    if total > hi + 0.01:
        warn = f"  ⚠️ 合计 {_h(total)} 超了上限 {hi}h"
    return [f"> {day:%m-%d} {WEEKDAY_CN[day.weekday()]} · {name}（假期学习 {_h(total)}，定额 {lo}–{hi}h）{warn}"] + lines


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--print"]
    week = args[0] if args else week_of(datetime.now())
    mon, sun = week_dates(week)
    cfg = H.study()

    print(f"# 假期学习块 · {week}（{mon:%m-%d} ~ {sun:%m-%d}）")
    print(f"# 定额：每天 {cfg.get('每天最少', 4)}–{cfg.get('每天最多', 6)}h"
          f"｜分配：{' / '.join(f'{k} {_h(float(v))}' for k, v in (cfg.get('分配') or {}).items())}")
    print()

    days = H.week_holidays(mon)
    if not days:
        print("（这一周没有法定节假日）")
    else:
        for d, name in days:
            if d.isoweekday() == 7 and cfg.get("周日用周决策模板", True):
                print(f"> {d:%m-%d} 周日 · {name}（假期）→ 沿用周决策的周日固定模板"
                      f"：周决策 12:05 ｜ 西语 2h 13:30–15:30 ｜ 数学科 2h 15:30–17:30 ｜"
                      f" 外语科 1.5h 18:30–20:00 ｜ 留白 20:00–22:30 = 深度 5.5h ✅（已落在 4–6h 内，别再叠加）")
                print()
                continue
            print("\n".join(blocks_for_day(d, name, cfg)))
            print()

    mk = H.week_makeup_days(mon)
    if mk:
        for d, name in mk:
            print(f"⚠️ {d:%m-%d} {WEEKDAY_CN[d.weekday()]} 是**调休上班日**（{name}）：学校那天可能补课，"
                  f"课表 ics 里没有 —— 要补课就手工加一条单次事件，然后重跑 `./打卡.bat {week}`。")
        print()

    print("# ↑ 复制到周决策的「① 本周任务」（📅 会在 ./同步日程.bat 时变成定时事件）")
    print("#   压到 4h：删掉最后一块，或把「数学科」改 1.5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
