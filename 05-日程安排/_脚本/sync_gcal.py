#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Obsidian 周决策笔记里的任务「推送」到 Google 日历 —— 秒级，无延迟。

与 iCal 插件（Gist 订阅）的区别：
  · iCal 插件 = 生成 .ics → Google 每隔 8~24 小时来抓一次（慢，但零配置）
  · 本脚本    = 直接调用 Google Calendar API 写入（秒级，需要一次性 OAuth）

幂等性设计：在**专用日历**里「全量重建」——每次同步先清空窗口内的全部事件，
再按笔记重新插入。所以改时间、改标题、删任务都不会产生重复事件。

用法：
    ./同步日历.bat --dry-run          # 只看会推送什么，不联网
    ./同步日历.bat                    # 真正同步
    ./同步日历.bat --check            # 检查授权是否有效
    ./同步日历.bat --completed drop   # 已完成的任务从日历移除（默认加 ✅ 前缀保留）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ─────────────────────────── 路径 ───────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]                      # <vault>/05-日程安排/_脚本 → <vault>


# 人改的配置住在 00-配置/（与引擎 _脚本/ 分家）；旧位置 _脚本/config.json 仍然兼容
def _resolve_config_file() -> Path:
    candidates = (VAULT / "05-日程安排/00-配置/同步配置.json", SCRIPT_DIR / "config.json")
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


CONFIG_FILE = _resolve_config_file()
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"          # OAuth 桌面客户端
SA_FILE = SCRIPT_DIR / "service-account.json"               # 服务账号密钥
TOKEN_FILE = SCRIPT_DIR / "token.json"

DEFAULT_CONFIG = {
    "calendar": "日程安排 (Obsidian)",
    "calendar_id": "",             # 服务账号模式必填（Google 日历 → 该日历 → 设置 → 日历 ID）
    "credentials_file": "",        # 留空 = 自动找 service-account.json，再找 credentials.json
    "timezone": "Asia/Shanghai",
    "scope": "app",                 # app = 只管理本脚本创建的日历（仅 OAuth 模式）；full = 完整日历权限
    "reminder_minutes": 10,
    "completed": "prefix",          # prefix = 加 ✅ 前缀保留；drop = 移除；keep = 原样保留
    "window_past_days": 14,
    "window_future_days": 180,
    "task_globs": ["05-日程安排/06-日志/*/????-W??.md", "05-日程安排/04-检查点与待核实.md"],
    "ics_files": ["05-日程安排/_资源/日历/学校课表-修正.ics"],
    "ics_color_id": "7",          # 课表事件的 Google 颜色（7 = Peacock 蓝绿）；留空 = 默认色
    "ics_reminder_minutes": 20,    # 上课提前提醒（分钟）
    "ics_skip_summary_prefixes": ["📚"],   # 跳过这些开头的条目（📚 = 周决策管理的自习块，避免重复）
}

SCOPES = {
    "app": ["https://www.googleapis.com/auth/calendar.app.created"],
    "full": ["https://www.googleapis.com/auth/calendar"],
}
SA_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ─────────────────────────── 解析 ───────────────────────────

TASK_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<body>.+?)\s*$")
DATE_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{1,2})")
# 优先认「紧跟在标记后面的日期」，避免把标题里提到的其它日期误当成任务日期
DATE_DUE_RE = re.compile(r"📅\s*(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{1,2})")
DATE_EMOJI_RE = re.compile(r"[➕⏳🛫📅✅]\s*(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{1,2})")
TIME_RE = re.compile(
    r"(?P<h1>\d{1,2}):(?P<mi1>\d{2})\s*[-–—~至]\s*(?P<h2>\d{1,2}):(?P<mi2>\d{2})"
)
EMOJI_RE = re.compile(r"[➕⏳🛫📅✅❌🔁]\s*")


def parse_tasks(vault: Path, globs: list[str], tz) -> list[dict]:
    """扫描周决策笔记，抽出带日期的任务。"""
    tasks: list[dict] = []
    for pattern in globs:
        for path in sorted(vault.glob(pattern)):
            if path.name.startswith("说明"):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                m = TASK_RE.match(line)
                if not m:
                    continue
                body = m.group("body")
                dm = DATE_DUE_RE.search(body) or DATE_EMOJI_RE.search(body) or DATE_RE.search(body)
                if not dm:
                    continue                      # 没有日期的任务不进日历

                start = datetime(
                    int(dm.group("y")), int(dm.group("m")), int(dm.group("d")), tzinfo=tz
                )
                span_date = dm.span()
                t_start = t_end = None
                span_time = None

                tm = TIME_RE.search(body)
                if tm:
                    h1, mi1, h2, mi2 = (int(tm.group(i)) for i in ("h1", "mi1", "h2", "mi2"))
                    t_start = start.replace(hour=h1, minute=mi1)
                    t_end = start.replace(hour=h2, minute=mi2)
                    if t_end <= t_start:              # 跨午夜（22:00-01:00）→ 次日
                        t_end += timedelta(days=1)
                    span_time = tm.span()

                # 从原文里挖掉「日期」和「时间区间」，剩下的才是标题
                title = body
                for a, b in sorted([s for s in (span_date, span_time) if s], reverse=True):
                    title = title[:a] + " " + title[b:]
                # 先把「其它带标记的日期」整段挖掉（必须在剥除表情字符之前）
                title = DATE_EMOJI_RE.sub(" ", title)
                title = re.sub(r"\s+", " ", EMOJI_RE.sub(" ", title)).strip(" 　-—:：、·*")
                title = title.replace("`", "").replace("**", "").strip()

                uid = hashlib.sha1(
                    f"{path.relative_to(vault)}::{line}".encode("utf-8")
                ).hexdigest()[:16]

                tasks.append(
                    {
                        "file": str(path.relative_to(vault)),
                        "line": lineno,
                        "done": m.group("mark").lower() == "x",
                        "title": title or "(未命名任务)",
                        "all_day": t_start is None,
                        "start": start,
                        "t_start": t_start,
                        "t_end": t_end,
                        "uid": uid,
                    }
                )
    tasks.sort(key=lambda t: (t["start"], t["all_day"], t["t_start"] or t["start"], t["title"]))
    return tasks


# ─────────────────────────── iCalendar（课表） ───────────────────────────


def _rel(path: Path) -> str:
    """库内文件给相对路径，库外（如 ~/Downloads）给绝对路径。"""
    try:
        return str(path.relative_to(VAULT))
    except ValueError:
        return str(path)


def _unfold(text: str) -> str:
    """iCalendar 长行折叠：CRLF + 空格/制表符 = 续行。"""
    return re.sub(r"\r?\n[ \t]", "", text)


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _parse_ics_dt(pairs, tz):
    """解析 DTSTART/DTEND；支持带 TZID 的本地时间与 VALUE=DATE 全天。"""
    if not pairs:
        return None
    key, raw = pairs[0]
    key, raw = key.upper(), raw.strip()
    if "VALUE=DATE" in key or (len(raw) == 8 and raw.isdigit()):
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=tz)
        except ValueError:
            return None
    is_utc = raw.endswith("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            dt = datetime.strptime(raw.rstrip("Z"), fmt)
        except ValueError:
            continue
        # 带 Z = UTC，要换算到本地时区；否则按本地时区理解
        return (dt.replace(tzinfo=timezone.utc).astimezone(tz) if is_utc else dt.replace(tzinfo=tz))
    return None


def parse_ics(path: Path, tz, win_lo: datetime, win_hi: datetime,
              cfg_skip_prefixes: tuple[str, ...] = ()) -> list[dict]:
    """把 .ics 里的 VEVENT（含 FREQ=WEEKLY 循环）展开成窗口内的一条条事件。"""
    raw = _unfold(path.read_text(encoding="utf-8", errors="ignore"))
    out: list[dict] = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.S):
        props: dict[str, list] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            props.setdefault(key.split(";")[0].upper(), []).append((key, val))

        start = _parse_ics_dt(props.get("DTSTART"), tz)
        if start is None:
            continue
        end = _parse_ics_dt(props.get("DTEND"), tz) or (start + timedelta(hours=1))
        duration = end - start
        all_day = "VALUE=DATE" in (props.get("DTSTART") or [("", "")])[0][0].upper()

        def first(key: str) -> str:
            got = props.get(key)
            return _unescape(got[0][1].strip()) if got else ""

        prefixes = cfg_skip_prefixes or ()
        if any(first("SUMMARY").startswith(pf) for pf in prefixes):
            continue          # 跳过「📚 自习块」这类由周决策管理的条目，避免重复

        exdates = set()
        for key, val in props.get("EXDATE", []):
            for piece in val.split(","):
                got = _parse_ics_dt([(key, piece)], tz)
                if got:
                    exdates.add(got)

        rrule = first("RRULE")
        until = None
        m = re.search(r"UNTIL=(\d{8}T\d{6})Z", rrule)
        if m:
            until = (
                datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
                .replace(tzinfo=timezone.utc)
                .astimezone(tz)
            )

        starts: list[datetime] = []
        if "FREQ=WEEKLY" in rrule:
            # 支持 INTERVAL=（隔周课）与 COUNT=（限次），学校导出的表这两种都可能出现
            mi = re.search(r"INTERVAL=(\d+)", rrule)
            step = timedelta(days=7 * int(mi.group(1)) if mi else 7)
            mc = re.search(r"COUNT=(\d+)", rrule)
            limit = int(mc.group(1)) if mc else None
            d, guard, emitted = start, 0, 0
            while d < win_hi and (until is None or d <= until) and guard < 400:
                if limit is not None and emitted >= limit:
                    break
                if d >= win_lo and d not in exdates:
                    starts.append(d)
                emitted += 1
                d += step
                guard += 1
        elif win_lo <= start < win_hi and start not in exdates:
            starts.append(start)

        base_uid = first("UID") or first("SUMMARY")
        for s in starts:
            out.append(
                {
                    "kind": "course",
                    "title": first("SUMMARY") or "(无标题)",
                    "all_day": all_day,
                    "start": s,
                    "t_start": None if all_day else s,
                    "t_end": None if all_day else s + duration,
                    "location": first("LOCATION"),
                    "description": first("DESCRIPTION"),
                    "uid": f"ics-{base_uid}-{s:%Y%m%d}",
                    "file": _rel(path),
                    "line": 0,
                    "done": False,
                }
            )
    return out


# ─────────────────────────── Google ───────────────────────────


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已生成默认配置：{CONFIG_FILE.relative_to(VAULT)}")
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def resolve_ics_paths(cfg: dict) -> list[Path]:
    """按配置展开课表 ics 路径；一个都没命中时退回「课表示例.ics」，让新库开箱即用。"""
    paths = [q for pattern in cfg.get("ics_files") or [] for q in sorted(VAULT.glob(pattern))]
    if not paths:
        sample = VAULT / "05-日程安排/_资源/日历/课表示例.ics"
        if sample.exists():
            print(
                "ℹ️  没找到配置里的课表文件，本次先用示例课表跑通流程。\n"
                "     换成你自己的课表：把文件放到 05-日程安排/_资源/日历/课表-当前.ics\n"
                "     （也可在 Claudian 里跑 /课表 导入）。"
            )
            return [sample]
    return paths


def find_credentials(cfg: dict) -> tuple[Path, str]:
    """返回 (密钥文件, 类型)，类型为 service_account 或 oauth。

    查找顺序：config 指定 → service-account.json → credentials.json → 本目录下任何
    看着像密钥的 *.json（服务账号密钥下载后名字是一长串，所以自动识别）。
    """
    candidates: list[Path] = []
    if cfg.get("credentials_file"):
        candidates.append(SCRIPT_DIR / cfg["credentials_file"])
    candidates += [SA_FILE, CREDENTIALS_FILE]
    candidates += [
        p for p in sorted(SCRIPT_DIR.glob("*.json"))
        if p.name not in {"config.json", "token.json", SA_FILE.name, CREDENTIALS_FILE.name}
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:                                          # noqa: BLE001
                continue
            if data.get("type") == "service_account":
                return path, "service_account"
            if "installed" in data or "web" in data:
                return path, "oauth"
    return None, "none"


def get_service(scope: list[str], cfg: dict, require_id: bool = True):
    """支持两种凭据：服务账号（推荐，无需发布/不过期）与 OAuth 桌面客户端。"""
    from googleapiclient.discovery import build

    cred_path, kind = find_credentials(cfg)

    # ── 服务账号：不经过同意屏幕，无发布/验证/令牌过期问题 ──
    if kind == "service_account":
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            str(cred_path), scopes=SA_SCOPES
        )
        try:
            email = json.loads(cred_path.read_text(encoding="utf-8")).get("client_email", "")
        except Exception:                                              # noqa: BLE001
            email = ""
        print(f"🔑 使用服务账号：{email or cred_path.name}")
        if require_id and not cfg.get("calendar_id"):
            sys.exit(
                "❌ 服务账号模式需要在 00-配置/同步配置.json 里填 calendar_id\n"
                "   取值方法：Google 日历网页版 → 左侧「我创建的」→ 日程安排 (Obsidian）\n"
                "             → 设置和共享 → 往下拉，复制「日历 ID」（形如 xxx@group.calendar.google.com）\n"
                "   并把服务账号邮箱加到该日历的「与特定用户共享」里（权限选「更改活动」）"
            )
        return build("calendar", "v3", credentials=creds)

    if kind == "none":
        sys.exit(
            f"❌ 没找到凭据文件。需要的文件（二选一）：\n"
            f"   · 服务账号（推荐）：{SA_FILE.relative_to(VAULT)}\n"
            f"   · OAuth 桌面客户端：{CREDENTIALS_FILE.relative_to(VAULT)}\n"
            f"   配置步骤见同目录的「README-首次配置.md」"
        )

    # ── OAuth 桌面客户端：需要同意屏幕 + 发布成「正式」 ──
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), scope)

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:                                   # noqa: BLE001
            print(f"⚠️  授权刷新失败（{exc}）")
            print("   → 常见原因：OAuth 应用停留在「测试」状态，刷新令牌 7 天就过期。")
            print("   → 两条路：① 把发布状态改成「正式」；② 改用服务账号（更省事）。")
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scope)
        print("正在打开浏览器授权（只此一次）…")
        creds = flow.run_local_server(port=0, prompt="consent")
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        TOKEN_FILE.chmod(0o600)
        print(f"✅ 授权已保存到 {TOKEN_FILE.relative_to(VAULT)}\n")

    return build("calendar", "v3", credentials=creds)


def assert_safe_calendar(cal_id: str) -> str:
    """兵兵保护：本脚本会清空目标日历窗口内的全部事件，绝不允许指向主日历。"""
    low = cal_id.strip().lower()
    if low == "primary" or low.endswith("@gmail.com") or low.endswith("@googlemail.com"):
        sys.exit(
            f"❌ 拒绝操作主日历（{cal_id}）！\n"
            f"   本脚本会清空目标日历窗口内的全部事件，指向主日历会删掉你的真实日程。\n"
            f"   请在 Google 日历里另建一个专用日历，并把它的「日历 ID」填到 00-配置/同步配置.json 的 calendar_id。"
        )
    return cal_id


def check_calendar_timezone(service, cal_id: str, cfg: dict, fix: bool = False) -> None:
    """日历自身时区 ≠ 配置时区时提醒（不影响已写入事件的时刻，但会影响手动新建的事件）。"""
    meta = _exec(service.calendars().get(calendarId=cal_id))
    cal_tz = meta.get("timeZone")
    want = cfg["timezone"]
    if not cal_tz or cal_tz == want:
        return
    if fix:
        _exec(service.calendars().patch(calendarId=cal_id, body={"timeZone": want}))
        print(f"🔧 已把日历时区 {cal_tz} → {want}")
        return
    print(f"⚠️  日历自身时区是 {cal_tz}，配置里是 {want}（不影响已写入事件的时刻）")
    print(f"   要改：./同步日历.bat --fix-calendar-tz")
    print(f"   ⚠️ 更重要的是**账号时区**：日历 App 按账号时区显示，账号若在别的时区，课会显示到前一天！")


def ensure_calendar(service, cfg: dict) -> str:
    if cfg.get("calendar_id"):
        cal_id = assert_safe_calendar(cfg["calendar_id"])
        _exec(service.calendars().get(calendarId=cal_id))
        return cal_id

    name = cfg["calendar"]
    page = None
    while True:
        res = service.calendarList().list(pageToken=page).execute()
        for item in res.get("items", []):
            if item.get("primary"):
                continue                     # 永不把主日历当目标
            if item.get("summary") == name:
                return assert_safe_calendar(item["id"])
        page = res.get("nextPageToken")
        if not page:
            break
    cal = (
        service.calendars()
        .insert(
            body={
                "summary": name,
                "timeZone": cfg["timezone"],
                "description": "由 Obsidian 周决策自动同步 —— 请勿手动添加事件，每次同步会全量重建。",
            }
        )
        .execute()
    )
    print(f"✅ 已创建专用日历：{name}（id={cal['id']}）")
    return cal["id"]


def _exec(request, attempts: int = 6):
    """带退避重试的 API 调用（批量写入会撞到每分钟配额）。"""
    for i in range(attempts):
        try:
            return request.execute()
        except Exception as exc:                                   # noqa: BLE001
            msg = str(exc)
            # 限流 / 服务端抖动
            transient = any(k in msg for k in ("rateLimitExceeded", "userRateLimitExceeded", "429", "503", "502"))
            # 本机代理不稳：SSL EOF、读超时、连接重置、DNS 抖动 —— 都重试
            network = isinstance(exc, (TimeoutError, OSError, ConnectionError)) or any(
                k in msg for k in ("SSLEOFError", "SSL", "timed out", "TimeoutError",
                                   "Connection reset", "RemoteDisconnected", "EOF occurred")
            )
            if (not transient and not network) or i == attempts - 1:
                raise
            wait = 2 ** i
            print(f"   ⏳ {'限流' if transient else '网络抖动'}，等 {wait}s 重试（{i + 1}/{attempts - 1}）…")
            time.sleep(wait)
    return None


def list_events(service, cal_id: str, t_min: str, t_max: str, source: str | None = None) -> list[dict]:
    """窗口内的事件；source 给定时只返回该来源（extendedProperties.private.source）。"""
    out, page = [], None
    while True:
        res = _exec(
            service.events().list(
                calendarId=cal_id,
                timeMin=t_min,
                timeMax=t_max,
                singleEvents=True,
                showDeleted=False,
                maxResults=2500,
                pageToken=page,
            )
        )
        for ev in res.get("items", []):
            src = (ev.get("extendedProperties", {}).get("private", {}) or {}).get("source")
            if source is None or src == source:
                out.append(ev)
        page = res.get("nextPageToken")
        if not page:
            break
    return out


def clear_events(service, cal_id: str, events: list[dict]) -> int:
    """删除给定事件（先收齐 id 再删，避免翻页错位）。未标记来源的事件不会传进来。"""
    for ev in events:
        _exec(service.events().delete(calendarId=cal_id, eventId=ev["id"]))
    return len(events)


def course_fingerprint(task: dict, cfg: dict) -> str:
    """课表事件的内容指纹：只有指纹变了才需要重新写入。"""
    parts = [
        task.get("title", ""),
        task["start"].strftime("%Y-%m-%dT%H:%M"),
        (task["t_start"] or task["start"]).strftime("%Y-%m-%dT%H:%M"),
        (task["t_end"] or task["start"]).strftime("%Y-%m-%dT%H:%M"),
        task.get("location", ""),
        task.get("description", ""),
        str(cfg.get("ics_color_id", "")),
        str(cfg.get("ics_reminder_minutes", "")),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def upsert_course(service, cal_id: str, task: dict, cfg: dict) -> str:
    """幂等写入一条课表事件（按 iCalUID）：新建或更新，不会重复。"""
    body = to_event(task, cfg)
    body["iCalUID"] = task["uid"]
    try:
        _exec(service.events().import_(calendarId=cal_id, body=body))
        return "import"
    except Exception:                                                  # noqa: BLE001
        found = _exec(service.events().list(calendarId=cal_id, iCalUID=task["uid"])).get("items", [])
        if not found:
            raise
        _exec(service.events().update(calendarId=cal_id, eventId=found[0]["id"], body=body))
        return "update"


def to_event(task: dict, cfg: dict) -> dict:
    tz = cfg["timezone"]
    done = task["done"]
    mode = cfg["completed"]
    is_course = task.get("kind") == "course"

    summary = task["title"]
    if done and mode == "prefix":
        summary = f"✅ {summary}"

    if is_course:
        minutes = int(cfg.get("ics_reminder_minutes", 20))
        body = {
            "summary": summary,
            "description": task.get("description") or f"来自 {task['file']}",
            "extendedProperties": {
                "private": {
                    "obsidianUid": task["uid"],
                    "source": "course",
                    "fp": course_fingerprint(task, cfg),
                }
            },
            "reminders": {"useDefault": False,
                          "overrides": [{"method": "popup", "minutes": minutes}]},
        }
        if task.get("location"):
            body["location"] = task["location"]
        if cfg.get("ics_color_id"):
            body["colorId"] = str(cfg["ics_color_id"])
    else:
        body = {
            "summary": summary,
            "description": f"来自 Obsidian：{task['file']} 第 {task['line']} 行",
            "extendedProperties": {"private": {"obsidianUid": task["uid"], "source": "task"}},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": int(cfg["reminder_minutes"])}],
            },
        }

    if task["all_day"]:
        body["start"] = {"date": task["start"].strftime("%Y-%m-%d")}
        body["end"] = {"date": (task["start"] + timedelta(days=1)).strftime("%Y-%m-%d")}
        body["reminders"] = {"useDefault": True}
    else:
        body["start"] = {"dateTime": task["t_start"].strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}
        body["end"] = {"dateTime": task["t_end"].strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}

    return body


# ─────────────────────────── 主流程 ───────────────────────────


def print_tasks(tasks: list[dict], cfg: dict) -> None:
    if not tasks:
        print("（窗口内没有带日期的任务）")
        return
    print(f"{'':2} {'日期':10} {'时间':14} 标题")
    print("─" * 76)
    for t in tasks:
        mark = "✅" if t["done"] else "·"
        when = t["start"].strftime("%m-%d %a")
        span = "全天" if t["all_day"] else f"{t['t_start']:%H:%M}–{t['t_end']:%H:%M}"
        print(f"{mark:2} {when:10} {span:14} {t['title']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="把周决策任务推送到 Google 日历（秒级）")
    ap.add_argument("--dry-run", action="store_true", help="只看会推送什么，不联网、不写日历")
    ap.add_argument("--check", action="store_true", help="只检查授权和日历是否可用")
    ap.add_argument("--list-calendars", action="store_true", help="列出凭据能访问的所有日历及其 ID（配置 calendar_id 时用）")
    ap.add_argument("--calendar", help="覆盖配置里的日历名")
    ap.add_argument("--completed", choices=["prefix", "drop", "keep"], help="已完成任务怎么处理")
    ap.add_argument("--ics", help="指定课表 ics（覆盖 config；支持绝对路径或库内相对路径）")
    ap.add_argument("--skip-ics", action="store_true", help="本次不动课表，只同步任务")
    ap.add_argument("--skip-tasks", action="store_true", help="本次不动任务，只同步课表")
    ap.add_argument("--force-ics", action="store_true", help="课表数量骤降时也强行写入")
    ap.add_argument("--fix-calendar-tz", action="store_true", help="把日历自身时区改成 config 里的时区")
    ap.add_argument("--allow-empty-ics", action="store_true", help="课表解析出 0 条时也执行（会清空课表）")
    ap.add_argument("--past-days", type=int, help="回溯多少天（默认取配置）")
    ap.add_argument("--future-days", type=int, help="向后多少天（默认取配置）")
    args = ap.parse_args()

    cfg = load_config()
    if args.calendar:
        cfg["calendar"] = args.calendar
    if args.completed:
        cfg["completed"] = args.completed
    if args.past_days is not None:
        cfg["window_past_days"] = args.past_days
    if args.future_days is not None:
        cfg["window_future_days"] = args.future_days

    tz = ZoneInfo(cfg["timezone"])
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    win_lo = today - timedelta(days=int(cfg["window_past_days"]))
    win_hi = today + timedelta(days=int(cfg["window_future_days"]))

    tasks = parse_tasks(VAULT, cfg["task_globs"], tz)
    in_window = [t for t in tasks if win_lo <= t["start"] < win_hi]

    if args.ics:
        given = Path(args.ics)
        ics_paths = [given if given.is_absolute() else (VAULT / given)]
    else:
        ics_paths = resolve_ics_paths(cfg)
    if args.ics:
        print(f"📚 本次课表来源（--ics 覆盖）：{args.ics}")

    courses: list[dict] = []
    if True:
        for ics_path in ics_paths:
            courses += parse_ics(
                ics_path, tz, win_lo, win_hi,
                tuple(cfg.get("ics_skip_summary_prefixes", ["📚"])),
            )
    in_window += courses
    in_window.sort(key=lambda t: (t["start"], t["all_day"], t["t_start"] or t["start"], t["title"]))

    print(f"📖 扫描：{', '.join(cfg['task_globs'])}")
    print(f"🕓 窗口：{win_lo:%Y-%m-%d} ~ {win_hi:%Y-%m-%d}（过去/未来 {cfg['window_past_days']}/{cfg['window_future_days']} 天）")
    print(f"📋 任务 {len(in_window) - len(courses)} 条（窗口内）｜📚 课表 {len(courses)} 条（从 .ics 展开）\n")
    print_tasks(in_window, cfg)
    print()

    if args.dry_run:
        print("（--dry-run：没有联网，也没有改动日历）")
        return 0

    pushable = [
        t
        for t in in_window
        if t.get("kind") != "course" and not (t["done"] and cfg["completed"] == "drop")
    ]

    service = get_service(SCOPES[cfg["scope"]], cfg, require_id=not args.list_calendars)

    if args.list_calendars:
        print("凭据能访问的日历（把第 1 列填进 00-配置/同步配置.json 的 calendar_id）：\n")
        page = None
        found = 0
        while True:
            res = service.calendarList().list(pageToken=page).execute()
            for item in res.get("items", []):
                print(f"{item['id']}\n    └─ 名称：{item.get('summary')}｜权限：{item.get('accessRole')}")
                found += 1
            page = res.get("nextPageToken")
            if not page:
                break
        if not found:
            print("（一个都没有）——说明日历还没共享给这个账号，回上一步做共享。")
        return 0

    if args.check:
        cal_id = ensure_calendar(service, cfg)
        print(f"✅ 授权有效｜日历可用：{cfg['calendar']}（id={cal_id}）")
        check_calendar_timezone(service, cal_id, cfg, fix=args.fix_calendar_tz)
        return 0

    cal_id = ensure_calendar(service, cfg)
    check_calendar_timezone(service, cal_id, cfg, fix=args.fix_calendar_tz)
    t_min, t_max = win_lo.isoformat(), win_hi.isoformat()

    # ── ① 课表：先做安全阀，再按 iCalUID 差量对账（只动变化的部分）──
    existing_courses = list_events(service, cal_id, t_min, t_max, source="course") if not args.skip_ics else []
    existing_by_uid = {ev.get("iCalUID"): ev for ev in existing_courses if ev.get("iCalUID")}

    if args.skip_ics:
        print("📚 --skip-ics：本次不动课表")
    elif cfg.get("ics_files"):
        if not courses and not args.allow_empty_ics:
            sys.exit(
                "❌ 课表解析出 0 条，已中止（不会删你日历里的课表）。\n"
                "   检查 00-配置/同步配置.json 的 ics_files 指向的文件是否存在、内容是否是课表；\n"
                "   确实要清空课表：加 --allow-empty-ics"
            )
        if existing_courses and len(courses) < len(existing_courses) * 0.5 and not args.force_ics:
            sys.exit(
                f"❌ 新课表只有 {len(courses)} 条，而日历里现有 {len(existing_courses)} 条（掉了超过一半），已中止。\n"
                f"   常见原因：ics 选错文件（比如只导了部分课程）、或学校导出的表结构变了。\n"
                f"   确认无误就加 --force-ics 再跑。"
            )

        desired = {c["uid"]: c for c in courses}
        stale = [ev for uid, ev in existing_by_uid.items() if uid not in desired]
        deleted_courses = clear_events(service, cal_id, stale)

        added = updated = skipped = 0
        for c in courses:
            ev = existing_by_uid.get(c["uid"])
            fp = course_fingerprint(c, cfg)
            if ev is not None and (ev.get("extendedProperties", {}).get("private", {}) or {}).get("fp") == fp:
                skipped += 1
                continue
            try:
                action = upsert_course(service, cal_id, c, cfg)
                added += action == "import"
                updated += action == "update"
            except Exception as exc:                                   # noqa: BLE001
                print(f"⚠️  课表跳过「{c['title']}」{c['start']:%m-%d}：{exc}")
        print(f"📚 课表：新增 {added}｜更新 {updated}｜未变 {skipped}｜删除过期 {deleted_courses}")

    # ── ② 任务：全量重建（数量小）──
    old_tasks = list_events(service, cal_id, t_min, t_max, source="task") if not args.skip_tasks else []
    if not args.skip_tasks:
        print(f"🧹 清空旧的计划事件：{clear_events(service, cal_id, old_tasks)} 条")

        ok = 0
        for i, t in enumerate(pushable, 1):
            try:
                _exec(service.events().insert(calendarId=cal_id, body=to_event(t, cfg)))
                ok += 1
            except Exception as exc:                                   # noqa: BLE001
                print(f"⚠️  跳过「{t['title']}」：{exc}")
        print(f"📤 计划事件：写入 {ok}/{len(pushable)} 条")

    print("   打开手机/网页版 Google 日历即可看到，无需等待。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
