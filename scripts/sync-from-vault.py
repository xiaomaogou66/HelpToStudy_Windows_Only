#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本地 Obsidian 库「单向」同步框架文件到 Windows 版仓库（发布用）。

设计要点（与项目一贯策略一致）：
  · 拆书统一走 MinerU 单流程（PDF），本地提取（pdfplumber/docx/epub）已下线。
  · 只拷白名单里的工作流文件；个人笔记 / 日记 / 密钥 / 课表 / 词库一律不拷。
  · 拷贝后做「Windows 措辞适配 → 通用化 → 上线前检查」，扫到个人信息就中止。

用 Python 写（而不是 .ps1）是为了跨平台可跑、可复现、可被两端共用。

用法（Windows / Linux 都一样）：
    python scripts/sync-from-vault.py
    python scripts/sync-from-vault.py --dry-run
    set VAULT=D:\\path\\to\\vault            # Windows 换库位置
    VAULT=/path/to/vault python scripts/sync-from-vault.py
"""

from __future__ import annotations

import argparse
import filecmp
import os
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
VAULT = pathlib.Path(os.environ.get("VAULT") or pathlib.Path.home() / "obsidian_vault")
# 通用版配置模板（00-配置/*.json、课表示例.ics、周表.tsv）已由 Linux 版仓库生成过一份，
# 这里直接取用，避免两端手写出现差异；找不到就跳过（并提示）。
TEMPLATE_REPO = pathlib.Path(os.environ.get("TEMPLATE_REPO") or pathlib.Path.home() / "HelpToStudy_Linux")

# ─────────────────── 白名单：从库拷什么 ───────────────────
COPY_PATHS = [
    "00-使用指南", "01-提示词库", "02-模板",
    "03-学习主题/📌 从这里开始.md", "04-教材分块/📖 教材分块说明.md",
    "AGENTS.md", "CLAUDE.md",
    "copilot/copilot-custom-prompts",
    ".claude/commands",
    ".pi/skills",
    ".obsidian/app.json", ".obsidian/appearance.json", ".obsidian/community-plugins.json",
    ".obsidian/core-plugins.json", ".obsidian/graph.json", ".obsidian/hotkeys.json",
    ".obsidian/templates.json", ".obsidian/daily-notes.json",
    ".obsidian/dataview", ".obsidian/quickadd", ".obsidian/templater-obsidian",
    "_工具/split_textbook.py",
    "05-日程安排/_脚本", "05-日程安排/06-日志/说明-怎么打卡.md",
    "05-日程安排/00-配置/多端同步.md",
]
# 从库拷目录时要排除的东西（个人数据 / 平台专属脚本 / 缓存）
EXCLUDE_NAMES = {
    "__pycache__", ".venv", ".打卡.log", "周表.tsv", "today.sh",
    "打卡.sh", "周文件夹.sh", "同步日历.sh", "同步日程.sh", "自检.sh",
    "同步日历.desktop",
}
EXCLUDE_GLOBS = ["🔒*", "calender-*", "service-account*", "token.json", "credentials.json", "*.tmp"]

# ─────────────────── Windows 措辞适配 ───────────────────
# 顺序重要：长串在前，避免半截替换
WINDOWS_MAP = [
    ("_工具/设置MinerU令牌.sh", "_工具/设置MinerU令牌.bat"),
    ("环境配置.sh", "环境配置.bat"),
    ("安装.sh", "安装.bat"),
    ("（Linux 版仅 MinerU 流程）", "（全走 MinerU，不做本地提取）"),
    ("Linux 版仅保留 MinerU 拆书：请提供 **PDF**（扫描版 / 数学书均可）；EPUB / Word 不支持。",
     "全走 MinerU 拆书：请提供 **PDF**（扫描版 / 数学书均可）；EPUB / Word 请先转成 PDF。"),
    ("目录/文件选择由 zenity 提供（环境配置.sh 会自动安装 zenity、xdg-utils）。",
     "目录/文件选择用系统自带的文件对话框。"),
    ("双击 `.desktop` 也能用", "双击 `同步日历.bat` 也能用"),
    ("终端 / 双击 `.desktop` 时超时", "终端 / 双击 `.bat` 时超时"),
    ("`_工具/拆书.sh`", "`_工具/拆书.bat`"),
    ("_工具/拆书.sh", "_工具/拆书.bat"),
    ("_工具/.venv/bin/python", r"_工具\.venv\Scripts\python.exe"),
    (".venv/bin/python", r".venv\Scripts\python.exe"),
    ("同步日程.sh", "同步日程.bat"),
    ("同步日历.sh", "同步日历.bat"),
    ("周文件夹.sh", "周文件夹.bat"),
    ("打卡.sh", "打卡.bat"),
    ("自检.sh", "自检.bat"),
    ("today.sh", "today.bat"),
    ("同步日历.desktop", "同步日历.bat"),
    ("python3 ", "python "),
    ("~/obsidian_vault/05-日程安排/_脚本", r"<你的库>\05-日程安排\_脚本"),
    ("cd ~/obsidian_vault/05-日程安排/_脚本 && ", "cd /d <你的库>\\05-日程安排\\_脚本 && "),
    ("chmod 600 ", "icacls <文件> /inheritance:r /grant:r \"%USERNAME%:R\"   rem 替代 chmod 600："),
]

# ─────────────────── 上线前检查 ───────────────────
# 个人词表放本地 scripts/scrub-map.local.txt（.gitignore 已排除），仓库只留 example
MAP_FILES = [REPO / "scripts/scrub-map.local.txt", REPO / "scripts/scrub-map.example.txt"]


def load_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for mf in MAP_FILES:
        if not mf.exists():
            continue
        for line in mf.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2 or len(parts[0]) < 2 or parts[0].startswith("<"):
                continue
            pairs.append((parts[0], parts[1]))
    return pairs


def copy_paths(dry: bool) -> int:
    n = 0
    for rel in COPY_PATHS:
        src = VAULT / rel
        dst = REPO / rel
        if not src.exists():
            print(f"  [缺失] {rel}")
            continue
        if dry:
            print(f"  [将拷] {rel}")
            n += 1
            continue
        if src.is_dir():
            for dp, dn, fns in os.walk(src):
                dn[:] = [d for d in dn if d not in EXCLUDE_NAMES]
                for fn in fns:
                    if (fn in EXCLUDE_NAMES or fn.startswith("🔒")
                            or any(pathlib.PurePath(fn).match(g) for g in EXCLUDE_GLOBS)):
                        continue   # 🔒* = 本地专属说明，永不外传
                    s = pathlib.Path(dp) / fn
                    d = dst / s.relative_to(src)
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s, d)
                    n += 1
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


def copy_templates(dry: bool) -> int:
    """通用版配置：优先从 Linux 版仓库取（已脱敏），取不到就提示手工核对。"""
    rels = [
        "05-日程安排/00-配置/规划配置.json",
        "05-日程安排/00-配置/底线规则.json",
        "05-日程安排/00-配置/同步配置.json",
        "05-日程安排/_资源/日历/课表示例.ics",
        "05-日程安排/_脚本/周表.tsv",
    ]
    n = 0
    for rel in rels:
        src = TEMPLATE_REPO / rel
        dst = REPO / rel
        if not src.exists():
            print(f"  [模板缺失] {rel}（在 {TEMPLATE_REPO} 里没有，请核对）")
            continue
        if dry:
            print(f"  [将写] {rel}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        n += 1
    return n


def adapt_and_scrub(dry: bool, pairs: list[tuple[str, str]]) -> tuple[int, int]:
    """Windows 措辞适配 + 通用化，只改「来自库」的路径，不碰本脚本 / README / CI。"""
    from_vault = tuple(p.split("/")[0] for p in COPY_PATHS if "/" in p) + (
        "00-", "01-", "02-", "03-", "04-", "05-",
    )
    root_files = {"AGENTS.md", "CLAUDE.md"}
    ext = {".md", ".py", ".sh", ".json", ".tsv", ".desktop", ".bat", ".ps1", ".txt"}
    touched = hits = 0
    for dp, dn, fns in os.walk(REPO):
        dn[:] = [d for d in dn if d not in {".git", "__pycache__", "dist"}]
        rel_dir = os.path.relpath(dp, REPO)
        for fn in fns:
            if rel_dir == ".":
                if fn not in root_files:
                    continue
            elif not rel_dir.startswith(from_vault):
                continue
            f = pathlib.Path(dp) / fn
            if f.suffix not in ext:
                continue
            try:
                t = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            o = t
            for a, b in WINDOWS_MAP:
                t = t.replace(a, b)
            for a, b in pairs:
                t = t.replace(a, b)
            if t != o:
                touched += 1
                hits += sum(o.count(a) for a, _ in WINDOWS_MAP) + sum(o.count(a) for a, _ in pairs)
                if not dry:
                    f.write_text(t, encoding="utf-8", newline="")
    return touched, hits


def privacy_check(pairs: list[tuple[str, str]]) -> bool:
    words = [a for a, _ in pairs if not a.startswith("<")]
    bad_files = list(REPO.rglob("🔒*")) + list(REPO.rglob("*隐私*")) + list(REPO.rglob("*.local.md"))
    if bad_files:
        print("  ❌ 本地专属说明不该进仓库：")
        for f in bad_files:
            print("     " + str(f.relative_to(REPO)))
        return False
    leaked = []
    for dp, dn, fns in os.walk(REPO):
        dn[:] = [d for d in dn if d not in {".git", "dist", "__pycache__", "scripts"}]
        for fn in fns:
            f = pathlib.Path(dp) / fn
            if f.suffix not in {".md", ".py", ".sh", ".json", ".tsv", ".bat", ".ps1", ".txt"}:
                continue
            try:
                t = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for w in words:
                if w in t:
                    leaked.append((str(f.relative_to(REPO)), w))
    if leaked:
        print("  ❌ 扫到疑似个人信息：")
        for f, w in leaked[:20]:
            print(f"     {f}   ← {w}")
        return False
    # 密钥 / 课表 / 日记 / 个人主题
    suspicious = [
        p for p in REPO.rglob("*")
        if p.is_file() and (
            p.name.startswith(("calender-", "service-account", "token.json", "credentials.json"))
            or "06-日志" in p.parts and p.parent.name[:4].isdigit()
            or p.suffix in {".ical"}
        )
    ]
    if suspicious:
        print("  ❌ 不该存在的文件：")
        for p in suspicious:
            print("     " + str(p.relative_to(REPO)))
        return False
    print("  ✅ 没扫到个人信息 / 密钥 / 日记 / 课表")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="从本地库同步到 Windows 版仓库")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    if not VAULT.is_dir():
        print(f"[错误] 找不到库：{VAULT}", file=sys.stderr)
        return 1
    pairs = load_pairs()
    print(f"==> 库：{VAULT}\n==> 仓库：{REPO}\n==> 替换表：{len(pairs)} 条")

    print("\n==> 1. 拷贝框架文件（白名单）")
    n = copy_paths(dry)
    print(f"    拷入 {n} 项")

    print("\n==> 2. 通用版配置（取自已脱敏的 Linux 版仓库）")
    m = copy_templates(dry)
    print(f"    写入 {m} 个")

    print("\n==> 3. Windows 措辞适配 + 通用化")
    touched, hits = adapt_and_scrub(dry, pairs)
    print(f"    {touched} 个文件 / {hits} 处")

    print("\n==> 4. 上线前检查")
    if dry:
        print("  [dry-run] 跳过")
        return 0
    ok = privacy_check(pairs)
    print("\n==> 5. 结果")
    files = [p for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts]
    print(f"    仓库文件数：{len(files)}")
    print("    下一步：cd %s && git status --short" % REPO)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())