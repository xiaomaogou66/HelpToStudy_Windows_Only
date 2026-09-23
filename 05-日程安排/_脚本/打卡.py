#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成本周「打卡页」：每天的打卡项由当周真实课表 + 规则表决定。

为什么要有它：打卡模板写死的话，周三（零深度自习日）和周六（有家教）会显示一样的条目，
既不准也让人不想勾。现在改成从**课表 + 规则**推：规则里说「哪门课 / 星期几 → 出什么项」，
课表里有那节课，那天才会出现那一项。规则全在 `00-配置/底线规则.json`，改规则不用动代码。

用法：
    ./打卡.bat              # 生成本周（或补齐缺失项，不动已有勾选）
    ./打卡.bat 2026-W39     # 指定周
    ./打卡.bat --print      # 只打印不上磁盘

写进哪：`05-日程安排/06-日志/<周号>/打卡.md`（周文件夹由 `周文件夹.bat` 建，
`/周决策` 会先跑它再跑本脚本；缺文件夹时本脚本也会自己补建）。
同一文件夹里还有：`<周号>.md`（周决策）、`YYYY-MM-DD.md`（日记）。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import sync_gcal as S  # noqa: E402  复用 ics 解析 + 配置

# 规则住在 00-配置/（人改的）；旧位置 _脚本/ 下的底线规则.json 仍然兼容
def _resolve_rules_file() -> Path:
    candidates = (VAULT / "05-日程安排/00-配置/底线规则.json", SCRIPT_DIR / "底线规则.json")
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


RULES_FILE = _resolve_rules_file()
LOG_DIR = VAULT / "05-日程安排/06-日志"   # 里面一周一个 <周号>/ 文件夹（见 周文件夹.bat）
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load_rules() -> dict:
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


def week_dates(week: str) -> tuple[datetime, datetime]:
    """'2026-W39' → (周一 00:00, 周日 23:59)，按 ISO 周（%G-W%V）。"""
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", week.strip())
    if not m:
        sys.exit(f"❌ 周号格式应为 2026-W39，收到：{week}")
    year, wk = int(m.group(1)), int(m.group(2))
    mon = datetime.fromisocalendar(year, wk, 1)
    return mon, mon + timedelta(days=6)


def week_of(d: datetime) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def courses_by_day(mon: datetime, sun: datetime, cfg: dict) -> dict:
    """{日期字符串: [(时间, 课程名, 教室)]}，只含这周的课。"""
    tz = S.get_tz(cfg["timezone"])
    lo = mon.replace(hour=0, minute=0, tzinfo=tz)
    hi = (sun + timedelta(days=1)).replace(hour=0, minute=0, tzinfo=tz)
    paths = S.resolve_ics_paths(cfg)
    out: dict[str, list] = {}
    for p in paths:
        for e in S.parse_ics(p, tz, lo, hi, tuple(cfg.get("ics_skip_summary_prefixes", ["📚"]))):
            if e["all_day"]:
                continue
            key = e["start"].strftime("%Y-%m-%d")
            out.setdefault(key, []).append(
                (e["t_start"].strftime("%H:%M"), e["t_end"].strftime("%H:%M"),
                 e["title"], e.get("location", ""))
            )
    for v in out.values():
        v.sort()
    return out


STOP_PREFIX = "停课 · "


def stopped_on(day: datetime, rules: dict) -> list[str]:
    """临时停课：规则里 例外.停课（或旧版顶层 停课）{日期: ['课程名 开始–结束']}。"""
    table = (rules.get("例外") or {}).get("停课") or rules.get("停课") or {}
    if not isinstance(table, dict):
        return []
    return [str(x) for x in (table.get(day.strftime("%Y-%m-%d")) or []) if isinstance(x, str)]


def _course_template(rules: dict) -> str | None:
    """每节课的条目模板（新版 每节课.模板，旧版 每节课自动成项.前缀 兜底）。"""
    cfg = rules.get("每节课") or rules.get("每节课自动成项") or {}
    if cfg.get("启用") is False:
        return None
    tpl = cfg.get("模板")
    if tpl:
        return tpl
    if cfg.get("前缀") is not None:
        return cfg.get("前缀", "") + "{课程名} {开始}–{结束}"
    return None


def _triggers(rules: dict) -> list[tuple[dict, list[str]]]:
    """归一化成 [(条件, [项目…])]。新版 `触发` + 旧版 `课程底线`/`每周固定` 都认。"""
    out: list[tuple[dict, list[str]]] = []
    for r in rules.get("触发") or []:
        out.append((r.get("当") or {}, [x for x in (r.get("项目") or []) if x]))
    for r in rules.get("课程底线") or []:                       # 旧格式兼容
        out.append(({"课程匹配": r.get("匹配", "")}, [x for x in (r.get("项目") or []) if x]))
    for r in rules.get("每周固定") or []:                        # 旧格式兼容
        out.append(({"星期": r.get("星期")}, [r["项目"]] if r.get("项目") else []))
    return out


def _fmt(text: str, course: tuple | None = None) -> str:
    """把 {课程名}/{开始}/{结束} 占位换成真实值（没有对应值时去掉占位）。"""
    name, t1, t2 = course or ("", "", "")
    return (text.replace("{课程名}", name).replace("{开始}", t1)
                .replace("{结束}", t2)).strip()


def build_items(day: datetime, courses: list, rules: dict) -> list[str]:
    """一天的打卡项 = 每节课一项（出勤）+ 停课记录 + 触发规则项 + 每天都有。"""
    items: list[str] = []

    # 临时停课：那节课从出勤打卡里去掉，改留一条已勾的「停课 · …」记录（不计缺勤）
    stopped = stopped_on(day, rules)
    if stopped:
        courses = [c for c in courses if not any(c[2] in s for s in stopped)]

    # 每节课单独一项（出勤打卡）——「上课就是上课」，不当作别的习惯的载体
    timed: list[tuple[str, str]] = []
    tpl = _course_template(rules)
    if tpl:
        for t1, t2, name, _loc in courses:
            timed.append((t1, _fmt(tpl, (name, t1, t2))))

    # 停课记录按它本来该在的时间位置插回去（规则里形如「专业课C 14:00–16:45」）
    for s in stopped:
        timed.append((s.split()[-1].split("–")[0], f"{STOP_PREFIX}{s}"))
    timed.sort(key=lambda kv: kv[0])
    items += [text for _t, text in timed]

    # 触发规则：条件命中就在今天生成对应项目，同类合并并列出承载的课
    merged: dict[str, dict] = {}
    for cond, projs in _triggers(rules):
        if not projs:
            continue
        pattern, weekday = cond.get("课程匹配"), cond.get("星期")
        hits: list[tuple] = []
        if pattern:
            try:
                rx = re.compile(pattern)
            except re.error:
                rx = re.compile(re.escape(pattern))
            hits = [(t1, name) for t1, _t2, name, _loc in courses if rx.search(name)]
            if not hits:
                continue                       # 课程条件没命中 → 这项今天不出现
        if weekday is not None:
            try:
                if int(weekday) != day.isoweekday():
                    continue
            except (TypeError, ValueError):
                continue
        for proj in projs:
            slot = merged.setdefault(proj, {"carriers": [], "course": None})
            slot["carriers"] += [f"{name[:6]} {t1}" for t1, name in hits]
            if slot["course"] is None and hits:
                slot["course"] = (hits[0][1], hits[0][0], "")

    for proj, slot in merged.items():
        text = _fmt(proj, slot["course"])
        carriers = slot["carriers"]
        items.append(f"{text}　（{' / '.join(carriers)}）" if carriers else text)
    items += [i for i in rules.get("每天都有", []) if i not in merged]
    return items


def render(week: str, days: list[tuple[datetime, list[str]]], existing: dict,
           created: str | None = None, rules: dict | None = None) -> str:
    rules = rules or {}
    mon, sun = week_dates(week)
    created_str = created or f"{datetime.now():%Y-%m-%d}"
    header = rules.get("打卡页说明") or (
        "**打卡项跟着课表走**：每节课一项（出勤）；其余底线项按 "
        "`00-配置/底线规则.json` 的规则自动生成。"
    )
    lines = [
        "---",
        "type: checkin",
        f"week: {week}",
        f"range: {mon:%Y-%m-%d} ~ {sun:%Y-%m-%d}",
        f"created: {created_str}",
        "---",
        "",
        f"# ✅ 打卡 · {week}（{mon:%m-%d} ~ {sun:%m-%d}）",
        "",
    ]
    lines += [f"> {ln}" for ln in ([header] if isinstance(header, str) else header)]
    lines += [
        ">",
        "> 勾完即打卡。**连续天数 = 每天所有打卡项都勾上的连续天数**（首页自动算）；",
        "> 今天勾完 +1，今天没勾完数字不动（不会归零）。",
        ">",
        "> **临时停课**（学校临时通知）：那天那节课不算缺勤——出勤项去掉，改留一条已勾的「停课 · …」记录。",
        "",
    ]
    for d, items in days:
        key = d.strftime("%m-%d")
        lines.append(f"## {d:%m-%d} {WEEKDAY_CN[d.weekday()]}")
        lines.append("")
        if not items:
            items = ["今天没崩（崩了也不补课）"]
        if True:
            for item in items:
                was = existing.get((key, item))
                # 停课是「事实记录」不是待办：默认已勾，且重跑也不会掉
                mark = "x" if (was or item.startswith(STOP_PREFIX)) else " "
                lines.append(f"- [{mark}] {d:%m-%d} · {item}")
        lines.append("")
    lines.append("> 打卡页由 `_脚本/打卡.bat` 生成；重复运行只补缺失项，**不会清掉你已勾的**。")
    lines.append("")
    return "\n".join(lines)


def parse_existing(path: Path) -> dict:
    """已勾状态 {(日期, 条目原文): True}，用于重复运行时不丢勾选。"""
    got: dict[tuple[str, str], bool] = {}
    if not path.exists():
        return got
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \[( |x|X)\] (\d{2}-\d{2}) · (.*)$", line)
        if m:
            got[(m.group(2), m.group(3).strip())] = m.group(1).lower() == "x"
    return got


def parse_created(path: Path) -> str | None:
    """保留首次生成时的 created（重跑不篡改历史）。"""
    if not path.exists():
        return None
    m = re.search(r"^created:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def main() -> int:
    args = [a for a in sys.argv[1:]]
    print_only = "--print" in args
    args = [a for a in args if a != "--print"]
    cfg = S.load_config()
    week = args[0] if args else week_of(datetime.now(S.get_tz(cfg["timezone"])))
    mon, sun = week_dates(week)
    full_week = week == week_of(datetime.now(S.get_tz(cfg["timezone"])))
    rules = load_rules()

    cbd = courses_by_day(mon, sun, cfg)
    days = []
    for i in range(7):
        d = mon + timedelta(days=i)
        courses = cbd.get(d.strftime("%Y-%m-%d"), [])
        days.append((d, build_items(d, courses, rules)))

    path = LOG_DIR / week / "打卡.md"     # 06-日志/<周号>/打卡.md
    text = render(week, days, parse_existing(path), parse_created(path), rules)

    if print_only:
        print(text)
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(text, encoding="utf-8")
    n_items = sum(len(i) for _d, i in days)
    print(f"{'♻️  已更新' if existed else '✅ 已生成'}：{path.relative_to(VAULT)}")
    print(f"   {week}（{mon:%m-%d} ~ {sun:%m-%d}）共 {n_items} 项打卡")
    for d, items in days:
        tag = " ".join(i.split("　")[0] for i in items) or "—"
        print(f"   {d:%m-%d} {WEEKDAY_CN[d.weekday()]}  {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
