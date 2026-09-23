#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ics 后端：把日程写成标准 .ics 文件（与 Google 日历后端**地位同等**）。

同一份事件来源，两个后端：
  · ics  （本文件）  → 写 `_资源/日程安排.ics`：零云依赖，可被 Obsidian iCal 插件、
                       云盘 / Gist / 手机日历订阅；换设备照样看得到。
  · gcal （同步日历.bat）→ 推到 Google 专用日历（服务账号 / OAuth），多端原生同步。

两个后端读**同一个** 00-配置/同步配置.json（课表源、窗口、提醒、已完成任务口径），
用的也是**同一套 UID**（笔记 ↔ 日历事件一一对应，不会出现两份重复日程）。

用法：
    ./同步日程.bat --后端 ics            # 等价于直接跑本脚本
    python 导出ics.py --dry-run        # 只报数，不写文件
    python 导出ics.py --out 某处.ical  # 换输出位置
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

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


import sync_gcal as S  # noqa: E402  复用任务/课表解析（同一套逻辑，不重复实现）

PLAN_CONFIG = VAULT / "05-日程安排/00-配置/规划配置.json"
DEFAULT_OUT = "05-日程安排/_资源/日程安排.ics"
UID_SUFFIX = "@obsidian-schedule"
PRODID = "-//AI 学习工作流//日程安排//CN"


def load_plan() -> dict:
    if PLAN_CONFIG.exists():
        return json.loads(PLAN_CONFIG.read_text(encoding="utf-8"))
    return {}


def collect(cfg: dict, win_lo: datetime, win_hi: datetime, ics_override: str | None) -> tuple[list, list]:
    """窗口内的事件：笔记任务 + 课表展开（与 Google 后端完全同一套解析）。"""
    tz = S.get_tz(cfg["timezone"])
    tasks = [t for t in S.parse_tasks(VAULT, cfg["task_globs"], tz) if win_lo <= t["start"] < win_hi]
    if ics_override:
        given = Path(ics_override)
        paths = [given if given.is_absolute() else VAULT / given]
    else:
        paths = S.resolve_ics_paths(cfg)
    courses: list = []
    for p in paths:
        courses += S.parse_ics(p, tz, win_lo, win_hi, tuple(cfg.get("ics_skip_summary_prefixes", ["📚"])))
    events = tasks + courses
    events.sort(key=lambda t: (t["start"], t["all_day"], t["t_start"] or t["start"], t["title"]))
    return events, courses


# ─────────────────────────── iCalendar 写出 ───────────────────────────

def _esc(text: str) -> str:
    """iCalendar 文本转义（反斜杠、分号、逗号、换行）。"""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """按 RFC 5545 折行（75 字节），且不切坏 UTF-8 汉字。"""
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > 73:
            out.append(cur)
            cur, size = ch, b
        else:
            cur += ch
            size += b
    out.append(cur)
    return "\r\n ".join(out)


def _safe_uid(raw: str) -> str:
    u = re.sub(r"[^0-9A-Za-z._-]", "-", str(raw))[:120].strip("-")
    return (u or "event") + UID_SUFFIX


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_vevent(task: dict, cfg: dict) -> list[str]:
    """一条事件 → VEVENT 行（含提醒）。任务与课表用同一套字段，只有分类/提醒不同。"""
    is_course = task.get("kind") == "course"
    title = task["title"]
    if task.get("done") and cfg.get("completed", "prefix") == "prefix":
        title = f"✅ {title}"

    uid = _safe_uid(task["uid"])
    stamp = _utc(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"SUMMARY:{_esc(title)}",
    ]
    if task["all_day"]:
        lines += [
            f"DTSTART;VALUE=DATE:{(task['t_start'] or task['start']).strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{((task['t_start'] or task['start']) + timedelta(days=1)).strftime('%Y%m%d')}",
        ]
    else:
        lines += [f"DTSTART:{_utc(task['t_start'])}", f"DTEND:{_utc(task['t_end'])}"]

    if is_course:
        lines.append("CATEGORIES:课表")
        desc = task.get("description") or f"来自课表 {task.get('file', '')}"
        if task.get("location"):
            lines.append(f"LOCATION:{_esc(task['location'])}")
        minutes = int(cfg.get("ics_reminder_minutes", 20))
    else:
        lines.append("CATEGORIES:任务")
        desc = f"来自 Obsidian：{task['file']} 第 {task['line']} 行"
        minutes = int(cfg.get("reminder_minutes", 10))

    lines.append(f"DESCRIPTION:{_esc(desc)}")
    # 回链：谁生成了它（排查「日历里这条是哪来的」时直接看这里）
    lines.append(f"X-OBSIDIAN-SOURCE:{_esc(task['file'])}")
    if not task["all_day"] and minutes > 0:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_esc(title)}",
            f"TRIGGER:-PT{minutes}M",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build_ics(events: list[dict], cfg: dict, plan: dict) -> str:
    tz = cfg["timezone"]
    name = (plan.get("同步") or {}).get("ics日历名") or "日程安排"
    refresh = (plan.get("同步") or {}).get("ics刷新间隔") or "PT1H"
    head = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(name)}",
        f"X-WR-TIMEZONE:{tz}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{refresh}",
        "X-PUBLISHED-TTL:PT1H",
    ]
    body: list[str] = []
    for ev in events:
        body += to_vevent(ev, cfg)
    return "\r\n".join(_fold(ln) for ln in head + body + ["END:VCALENDAR"]) + "\r\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="把日程写成 .ics（ics 后端）")
    ap.add_argument("--dry-run", action="store_true", help="只报数，不写文件")
    ap.add_argument("--out", help=f"输出位置（相对库根；默认 {DEFAULT_OUT}）")
    ap.add_argument("--ics", help="指定课表 ics（覆盖配置）")
    ap.add_argument("--past-days", type=int)
    ap.add_argument("--future-days", type=int)
    args = ap.parse_args()

    cfg = S.load_config()
    plan = load_plan()
    if args.past_days is not None:
        cfg["window_past_days"] = args.past_days
    if args.future_days is not None:
        cfg["window_future_days"] = args.future_days

    tz = S.get_tz(cfg["timezone"])
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    win_lo = today - timedelta(days=int(cfg["window_past_days"]))
    win_hi = today + timedelta(days=int(cfg["window_future_days"]))

    events, courses = collect(cfg, win_lo, win_hi, args.ics)
    out_rel = args.out or (plan.get("同步") or {}).get("ics输出") or DEFAULT_OUT
    out = Path(out_rel)
    out = out if out.is_absolute() else VAULT / out

    print("🧩 后端：ics（本机文件）")
    print(f"🕓 窗口：{win_lo:%Y-%m-%d} ~ {win_hi:%Y-%m-%d}（过去/未来 {cfg['window_past_days']}/{cfg['window_future_days']} 天）")
    print(f"📋 任务 {len(events) - len(courses)} 条｜📚 课表 {len(courses)} 条 → 共 {len(events)} 条事件")
    print(f"📄 输出：{out_rel}{'（已存在，将原子替换）' if out.exists() else ''}")

    if args.dry_run:
        print("（--dry-run：没有写文件）")
        return 0

    text = build_ics(events, cfg, plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    tmp.replace(out)                       # 原子替换：订阅方不会读到半截文件
    print(f"✅ 已写出 {out.relative_to(VAULT)}（{len(text.encode('utf-8')) / 1024:.1f} KB，{len(events)} 条事件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())