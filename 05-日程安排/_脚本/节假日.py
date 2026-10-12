#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法定节假日：读 `05-日程安排/00-配置/节假日.json`，给 打卡.py / sync_gcal.py / 假期块.py 共用。

一份配置三处生效：
  · 打卡页     —— 放假日不出勤，改留一条已勾的「假期 · 节日名」；并挂「假期学习 4–6 小时」
  · 本机 .ics  —— 放假日那天的课表事件自动跳过（等价于自动加 EXDATE）
  · Google 日历 —— 同上（两个后端共用 sync_gcal.parse_ics）
  · 假期块.bat  —— 假期每天 4–6h 学习定额，生成可直接贴进周决策的任务行
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
CONFIG = VAULT / "05-日程安排/00-配置/节假日.json"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_STUDY = {
    "每天最少": 4,
    "每天最多": 6,
    "分配": {"西语": 2.5, "数学科": 2, "外语科": 1.5},
    "时段": [["09:30", "12:00"], ["14:00", "16:00"], ["16:30", "18:00"]],
    "科目名": {"西语": "外语精读", "数学科": "数学科", "外语科": "外语科"},
    "周日用周决策模板": True,
}


def load() -> dict:
    """读配置；文件缺失/坏掉时返回空表（不抛异常——绝不能因为节假日配置坏了就让打卡跑不动）。"""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _clean_table(key: str) -> dict[str, str]:
    table = load().get(key) or {}
    if not isinstance(table, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in table.items():
        if k.startswith("_") or not DATE_RE.match(str(k)):
            continue
        if isinstance(v, dict):                                 # 兼容 {日期: {节日:…}}
            v = v.get("节日") or v.get("名称") or "假期"
        out[str(k)] = str(v)
    return out


def holidays() -> dict[str, str]:
    """{YYYY-MM-DD: 节日名} —— 放假日。"""
    return _clean_table("放假")


def makeup_days() -> dict[str, str]:
    """{YYYY-MM-DD: 节日名} —— 官方调休上班日（那天可能要补课）。"""
    return _clean_table("调休上班")


def study() -> dict:
    cfg = dict(DEFAULT_STUDY)
    got = load().get("假期学习") or {}
    if isinstance(got, dict):
        cfg.update({k: v for k, v in got.items() if not str(k).startswith("_")})
    return cfg


def holiday_name(day: date | datetime | str) -> str | None:
    return holidays().get(_key(day))


def is_makeup(day: date | datetime | str) -> str | None:
    return makeup_days().get(_key(day))


def holiday_dates() -> frozenset[str]:
    """给 sync_gcal.parse_ics 用的跳过集。"""
    return frozenset(holidays())


def week_holidays(mon: date | datetime) -> list[tuple[date, str]]:
    """这一周（周一起 7 天）里的放假日 → [(日期, 节日名)]。"""
    m = mon.date() if isinstance(mon, datetime) else mon
    out: list[tuple[date, str]] = []
    for i in range(7):
        d = m + timedelta(days=i)
        name = holiday_name(d)
        if name:
            out.append((d, name))
    return out


def week_makeup_days(mon: date | datetime) -> list[tuple[date, str]]:
    m = mon.date() if isinstance(mon, datetime) else mon
    out: list[tuple[date, str]] = []
    for i in range(7):
        d = m + timedelta(days=i)
        name = is_makeup(d)
        if name:
            out.append((d, name))
    return out


def study_quota_text(cfg: dict | None = None) -> str:
    """'4–6 小时' —— 打卡项里那个占位符。"""
    cfg = cfg or study()
    return f"{cfg.get('每天最少', 4)}–{cfg.get('每天最多', 6)} 小时"


def merge_into_config(new_holidays: dict[str, str], new_makeup: dict[str, str],
                      years: list[int], source: str) -> dict:
    """把新拉的放假/调休表并进 `00-配置/节假日.json`（**保留**人工键：假期学习、说明等）。

    只覆盖 `放假` / `调休上班` / `更新`，其余原样不动。
    """
    cfg = load()
    old_holidays = holidays()
    old_makeup = makeup_days()
    # 只替换「本次涉及的年份」，别的年份保留（避免拉了 2026 把 2027 冲掉）
    keep_years = {str(y) for y in years}
    merged_h: dict[str, str] = {k: v for k, v in old_holidays.items() if k[:4] not in keep_years}
    merged_m: dict[str, str] = {k: v for k, v in old_makeup.items() if k[:4] not in keep_years}
    merged_h.update(new_holidays)
    merged_m.update(new_makeup)

    cfg.pop("_数据源", None)
    cfg["放假"] = dict(sorted(merged_h.items()))
    cfg["调休上班"] = dict(sorted(merged_m.items()))
    cfg["更新"] = {
        "上次": f"{datetime.now():%Y-%m-%d}",
        "年份": sorted({int(y) for y in (list(keep_years | {k[:4] for k in merged_h}) or []) if str(y).isdigit()}),
        "数据源": [source],
        "_注意": "当年的安排一般在前一年 11 月公布；没出之前拉回来是空的，出了以后再跑一次即可。",
    }
    return cfg


def _key(day: date | datetime | str) -> str:
    if isinstance(day, str):
        return day[:10]
    if isinstance(day, datetime):
        return day.strftime("%Y-%m-%d")
    return day.strftime("%Y-%m-%d")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        d = sys.argv[1]
        print(holiday_name(d) or is_makeup(d) or "不是放假日，也不是调休上班日")
    else:
        h, m = holidays(), makeup_days()
        print(f"放假日 {len(h)} 天｜调休上班日 {len(m)} 天")
        print(f"假期学习定额：{study_quota_text()}")
        for k in sorted(h):
            print(f"  🎌 {k} {h[k]}")
        for k in sorted(m):
            print(f"  🔁 {k} 调休上班（{m[k]}）")
