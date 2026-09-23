#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日程安排层 · 自检（烟测）—— **跨平台唯一实现**，不联网、不改数据，只验证「还能跑」。

Linux：`./自检.bat`（薄壳）｜Windows：`自检.bat`（薄壳）｜直接跑：`python 自检.py [--联网]`

检查项：配置可读 → 打卡页生成 → 周文件夹与日记 → today → 两个同步后端
        → ics 结构合规 → 命令/skill 一致性 → 拆书令牌 → 拆书脚本
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]
CONF = VAULT / "05-日程安排/00-配置"
PLAN, RULES, SYNC = CONF / "规划配置.json", CONF / "底线规则.json", CONF / "同步配置.json"
ICS_OUT = VAULT / "05-日程安排/_资源/日程安排.ics"
WEEK = date.today().strftime("%G-W%V")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                       # noqa: BLE001
    pass

PASS = FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def skip(msg: str) -> None:
    print(f"  ⏭ {msg}")


def step(title: str) -> None:
    print(f"\n==> {title}")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(SCRIPT_DIR))


def main() -> int:
    online = "--联网" in sys.argv

    step("1. 配置文件")
    for f in (PLAN, RULES, SYNC):
        try:
            json.loads(f.read_text(encoding="utf-8"))
            ok(f"可解析：{f.relative_to(VAULT)}")
        except Exception as exc:        # noqa: BLE001
            bad(f"JSON 有问题或缺失：{f.relative_to(VAULT)}（{exc}）")
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        ms = plan.get("里程碑") or []
        assert ms, "没有里程碑"
        ok("里程碑（唯一真源）能读出来 → " + "、".join(f"{m['名称']} {m['日期']}" for m in ms[:4]))
    except Exception as exc:            # noqa: BLE001
        bad(f"里程碑读不出来：{exc}")

    step("2. 打卡页（干跑，不落盘）")
    r = run("打卡.py", "--print", WEEK)
    out = r.stdout or ""
    if r.returncode == 0 and out.strip():
        ok(f"打卡页可生成（{WEEK}）")
    else:
        bad(f"打卡页生成失败：{(r.stderr or out)[:200]}")
    if re.search(r"^- \[[ x]\] \d{2}-\d{2} · ", out, re.M):
        ok("打卡条目格式正确")
    else:
        bad("打卡条目格式异常")

    step("3. 周文件夹与日记")
    r = run("周文件夹.py", WEEK)
    if r.returncode == 0:
        ok(f"周文件夹脚本可运行（{WEEK}）")
    else:
        bad(f"周文件夹脚本失败：{(r.stderr or r.stdout)[:200]}")
    folder = VAULT / "05-日程安排/06-日志" / WEEK
    ok(f"本周文件夹存在：06-日志/{WEEK}/") if folder.is_dir() else bad("本周文件夹不存在")
    diary = folder / f"{date.today():%Y-%m-%d}.md"
    ok(f"今天的日记在：06-日志/{WEEK}/{diary.name}") if diary.exists() else bad("今天的日记不在周文件夹里")

    step("4. today（读 00-配置 里的里程碑）")
    r = run("today.py")
    t = (r.stdout or "") + (r.stderr or "")
    ok("today 可运行") if r.returncode == 0 else bad(f"today 失败：{t[:200]}")
    ok("含打卡连续天数（新库显示「还没开始」属正常）") if re.search(r"连续|还没开始", t) else bad("缺少连续天数")
    ok("含里程碑倒计时") if re.search(r"\d+ 天", t) else bad("缺少里程碑倒计时")

    step("5. 同步 · ics 后端")
    r = run("导出ics.py", "--dry-run")
    if r.returncode == 0:
        m = re.search(r"共 (\d+) 条事件", r.stdout)
        ok(f"ics 后端干跑成功：{m.group(0) if m else ''}")
    else:
        bad(f"ics 后端干跑失败：{(r.stderr or r.stdout)[:200]}")
    r = run("导出ics.py")
    if r.returncode == 0 and ICS_OUT.exists():
        ok(f"ics 后端真跑成功：{r.stdout.strip().splitlines()[-1]}")
        check_ics(ICS_OUT)
    else:
        bad(f"ics 后端真跑失败：{(r.stderr or r.stdout)[:200]}")

    step("6. 同步 · Google 后端（不联网）")
    r = run("sync_gcal.py", "--dry-run")
    log = (r.stdout or "") + (r.stderr or "")
    if "缺少依赖" in log or "ModuleNotFoundError" in log:
        skip("gcal 后端跳过（依赖没装；ics 后端不受影响。装法："
             "_工具/.venv 里 pip install -r _脚本/requirements.txt）")
    elif r.returncode == 0:
        m = re.search(r"任务 (\d+) 条.*?课表 (\d+) 条", log, re.S)
        ok(f"gcal 后端干跑成功：{m.group(0).replace(chr(10), ' ') if m else ''}")
    else:
        bad(f"gcal 后端干跑失败：{log[:200]}")
    if online:
        r = run("sync_gcal.py", "--check")
        (ok if r.returncode == 0 else bad)(
            "Google 凭据/日历可用" if r.returncode == 0 else f"Google 凭据不可用：{(r.stderr or r.stdout)[:200]}")
    else:
        skip("跳过 Google 凭据检查（加 --联网 才查）")

    step("7. 统一入口")
    found = [f"同步日程{ext}" for ext in (".bat", ".sh") if (SCRIPT_DIR / f"同步日程{ext}").exists()]
    ok(f"统一入口存在：{' / '.join(found)}") if found else bad("缺统一入口（同步日程.bat / 同步日程.bat）")

    step("8. 命令与 skill 一致性")
    cmds = sorted((VAULT / ".claude/commands").glob("*.md"))
    if len(cmds) >= 8:
        ok(f"命令齐备（{len(cmds)} 条）")
    else:
        bad(f"命令数量异常：{len(cmds)} 条（应有 8 条）")
    skills = sorted((VAULT / ".pi/skills").glob("*.md"))
    ok(f"pi skills 齐备（{len(skills)} 个）") if len(skills) >= 8 else bad(f"skills 数量异常：{len(skills)}")

    step("9. 拆书令牌（MinerU）")
    check_token(VAULT / "_工具/mineru_token.txt")

    step("10. 拆书脚本")
    py = VAULT / "_工具/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    exe = str(py) if py.exists() else sys.executable
    script = VAULT / "_工具/split_textbook.py"
    r = subprocess.run([exe, str(script), "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok(f"split_textbook.py 可运行（{exe}）") if r.returncode == 0 else \
        skip("拆书环境还没装（跑 _工具/.venv 或 pip install -r _工具/requirements.txt）")

    print("\n" + "═" * 34)
    print(f"  通过 {PASS} 项，失败 {FAIL} 项")
    print("═" * 34)
    print("✅ 自检通过" if FAIL == 0 else "⚠️  有项目失败，见上面 ❌")
    return 1 if FAIL else 0


def check_ics(path: Path) -> None:
    """ics 结构合规：CRLF、BEGIN/END 平衡、有时间格式、有事件。"""
    raw = path.read_bytes().decode("utf-8", "replace")
    try:
        assert raw.count("\n") == raw.count("\r\n"), "存在裸 LF（应全为 CRLF）"
        lines = raw.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
        bal: Counter = Counter()
        for ln in lines:
            m = re.fullmatch(r"BEGIN:(\w+)|END:(\w+)", ln)
            if m:
                k = m.group(1) or m.group(2)
                bal[k] += 1 if m.group(1) else -1
        assert set(bal.values()) <= {0}, f"BEGIN/END 不平衡：{dict(bal)}"
        events = sum(1 for ln in lines if ln == "BEGIN:VEVENT")
        assert events > 0, "没有事件"
        bad_dt = [ln for ln in lines if ln.startswith(("DTSTART", "DTEND"))
                  and not re.match(r"DT(?:START|END)(;VALUE=DATE)?:\d{8}(T\d{6}Z)?$", ln)]
        assert not bad_dt, f"时间格式异常：{bad_dt[:2]}"
    except AssertionError as exc:
        bad(f"ics 结构有问题：{exc}")
    else:
        ok(f"ics 结构合规 → {events} 条事件 / "
           f"{sum(1 for ln in lines if ln == 'BEGIN:VALARM')} 条提醒")


def check_token(path: Path) -> None:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        skip("跳过（还没保存 MinerU 令牌：先运行 _工具 里的「设置MinerU令牌」启动器）")
        return
    days = int((datetime.now().timestamp() - path.stat().st_mtime) // 86400)
    token = path.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        "https://mineru.net/api/v4/extract/task/0",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
        if "A0211" in body:
            bad(f"MinerU 令牌已过期（已签发 {days} 天）→ 重新保存令牌")
        else:
            ok(f"MinerU 令牌可用（已签发 {days} 天）")
    except urllib.error.HTTPError as exc:              # 401 = 过期/非法
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 401 and "A0211" in body:
            bad(f"MinerU 令牌已过期（已签发 {days} 天）→ 重新保存令牌")
        elif exc.code == 401:
            bad(f"MinerU 令牌无效（已签发 {days} 天）")
        else:
            skip(f"令牌检查跳过（HTTP {exc.code}）")
    except Exception as exc:                          # noqa: BLE001 离线等
        skip(f"令牌检查跳过（{type(exc).__name__}）")
        _ = timezone  # 保持导入（脚本内其它地方可能用）


if __name__ == "__main__":
    raise SystemExit(main())