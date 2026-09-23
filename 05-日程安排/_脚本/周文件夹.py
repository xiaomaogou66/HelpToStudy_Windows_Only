#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为一个 ISO 周建「周文件夹」，并预建周一~周日 7 篇日记。

背景：`06-日志/` 以前是平铺的（`2026-09-14.md`、`2026-W38.md` 混在一起），
翻一个月就找不着东西。现在改成**一周一个文件夹**：

    05-日程安排/06-日志/2026-W38/          ← 一周的日志都放这里
        ├── 2026-W38.md      ← 本周打卡页（由 打卡.bat 写进同一文件夹）
        ├── 2026-09-14.md    ← 周一日记
        ├── …
        └── 2026-09-20.md    ← 周日记

Obsidian 的「日记」格式已设成 `GGGG-[W]WW/YYYY-MM-DD`，
所以 Ctrl+P →「日记：打开今天的日记」会自动落进对应的周文件夹（不会重复建）。
这个脚本的职责是**把文件夹和 7 篇日记先备好**，让 `/周决策` 之后整周开箱即用。

用法：
    ./周文件夹.bat              # 今天所在的周
    ./周文件夹.bat 2026-W39     # 指定周
    ./周文件夹.bat --print      # 只打印要建什么，不落盘
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

def _force_utf8_io() -> None:
    """Windows 上输出被管道捕获时默认不是 UTF-8，中文会触发 UnicodeEncodeError。

    交互式双击 .bat 有 `chcp 65001` 兜着，但 CI / 重定向 / 被别的脚本调用时必须自己设。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # noqa: BLE001
            pass


_force_utf8_io()

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
LOG_DIR = VAULT / "05-日程安排/06-日志"
TEMPLATE = VAULT / "02-模板/日记.md"

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def week_of(d: datetime) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_dates(week: str) -> tuple[datetime, datetime]:
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", week.strip())
    if not m:
        sys.exit(f"❌ 周号格式应为 2026-W39，收到：{week}")
    mon = datetime.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return mon, mon + timedelta(days=6)


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--print"]
    print_only = "--print" in sys.argv[1:]
    week = args[0] if args else week_of(datetime.now())
    mon, sun = week_dates(week)
    week_dir = LOG_DIR / week

    if not TEMPLATE.exists():
        sys.exit(f"❌ 找不到日记模板：{TEMPLATE.relative_to(VAULT)}")
    tpl = TEMPLATE.read_text(encoding="utf-8")

    created, kept = [], []
    for i in range(7):
        d = mon + timedelta(days=i)
        path = week_dir / f"{d:%Y-%m-%d}.md"
        if path.exists():
            kept.append(path.name)
            continue
        if not print_only:
            week_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(tpl.replace("{{date}}", f"{d:%Y-%m-%d}"), encoding="utf-8")
        created.append(path.name)

    rel = week_dir.relative_to(VAULT)
    print(f"📁 {week}（{mon:%m-%d} ~ {sun:%m-%d}）→ {rel}")
    if created:
        verb = "将生成" if print_only else "已生成"
        print(f"   {verb} {len(created)} 篇日记：" + " / ".join(created))
    if kept:
        print(f"   已存在（未动）{len(kept)} 篇：" + " / ".join(kept))
    if not created and not kept:
        print("   （无事可做）")
    print(f"   打卡页由 ./打卡.bat {week} 写进同一个文件夹")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
