#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把厚教材 PDF 拆成适合 AI 对话的小分块笔记（**全走 MinerU 云端识别**，不做本地提取）。

用法:
    python split_textbook.py "教材.pdf" --out "04-教材分块" --ocr mineru --mineru-token "你的Token"
    python split_textbook.py "00-MinerU解析全文.md" --out "04-教材分块" --split-mode chapter

参数:
    --max-chars / --overlap   已停用：一章一个文件，不再按字数切块

输出:
    在输出目录下生成 <书名>/ 文件夹，内含 00-教材信息.md、00-目录.md、
    01-全书大纲.md（章节大纲 + 进度勾选）以及按章节切好的 markdown 笔记。
    一章一个文件，章节内部不再切分，公式不会因截断显示错误。
    识别不到章节时全书保存为一个文件并提示校准，绝不乱切。
    仅支持 PDF（MinerU 云端 OCR，公式转 LaTeX）与 MinerU 解析全文 .md 重切分。

安全与防重复:
    每本书生成稳定的 book_id；重复拆分同一本书不会产生重复文件夹，
    旧文件会自动备份到库外 ~/obsidian_backups/拆书/<书名>/ 后原地更新（最多保留 5 份历史）。
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import date
from pathlib import Path

try:
    _out_enc = os.environ.get("SPLIT_OUTPUT_ENCODING") or "utf-8"
    sys.stdout.reconfigure(encoding=_out_enc, errors="replace")
    sys.stderr.reconfigure(encoding=_out_enc, errors="replace")
except Exception:
    pass

SUPPORTED = {".pdf"}

# 章节词：英文 / 意大利语 / 外语（含常见 OCR 无重音变体）
CHAPTER_WORD = r"(?:chapter|chap\.?|capitolo|capitulo|cap[íi]tulo|cap\.?)"

# 锚点/目录用章节词（比 CHAPTER_WORD 更全：含 Lesson/Unit/Lezione 等）
CHAPTER_WORD_ANCHOR = (
    r"(?:chapter|chap\.?|lesson|unit|part|module|chapitre|"
    r"capitolo|capitulo|cap[íi]tulo|lezione|lecci[óo]n|le[çc][oó]n|"
    r"unidad|unità|unita|parte|m[óo]dulo|modulo|secci[óo]n|sezione)"
)

CHAPTER_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9一二三四五六七八九十百千万零〇]+\s*[章节卷篇部讲课]"
    r"|Chapter\s+\d+"
    r"|Lesson\s+\d+"
    r"|Unit\s+\d+"
    r"|Part\s+[IVX\d]+"
    r"|Module\s+\d+"
    r"|Cap[íi]tulo\s+\d+"
    r"|Capitolo\s+\d+"
    r"|Capitulo\s+\d+"
    r"|Lecci[óo]n\s+\d+"
    r"|Lezione\s+\d+"
    r"|Unidad\s+\d+"
    r"|Unit[àa]\s+\d+"
    r"|Parte\s+[IVX\d]+"
    r"|M[óo]dulo\s+\d+"
    r"|Modulo\s+\d+"
    r"|Secci[óo]n\s+\d+"
    r"|Sezione\s+\d+"
    r")\s*[:：.、．\-—–]?\s*(.*)$",
    re.IGNORECASE,
)

# MinerU 云端识别：可执行文件与 Token 文件的位置（可移植解析）
def _resolve_mineru_cli() -> str:
    """按顺序查找 mineru-open-api：环境变量 > 本库虚拟环境（Linux/Windows）> 常见安装位置。"""
    for env_name in ("AIWF_MINERU_CLI", "MINERU_CLI"):
        env = os.environ.get(env_name, "").strip()
        if env:
            return env
    candidates = [
        Path(__file__).resolve().parent / ".venv" / "bin" / "mineru-open-api",
        Path(__file__).resolve().parent / ".venv" / "Scripts" / "mineru-open-api.exe",
        Path.home() / "obsidian-vault-mcp" / ".venv" / "Scripts" / "mineru-open-api.exe",
        Path(r"D:\obsidian-vault-mcp\.venv\Scripts\mineru-open-api.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return str(candidates[0])


def _resolve_mineru_token_file() -> Path:
    """按顺序查找 Token 文件：环境变量 > 本库 _工具 > 常见安装位置。"""
    for env_name in ("AIWF_MINERU_TOKEN_FILE", "MINERU_TOKEN_FILE"):
        env = os.environ.get(env_name, "").strip()
        if env:
            return Path(env)
    candidates = [
        Path(__file__).resolve().parent / "mineru_token.txt",
        Path.home() / "obsidian-vault-mcp" / "mineru_token.txt",
        Path(r"D:\obsidian-vault-mcp\mineru_token.txt"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


MINERU_DEFAULT_CLI = _resolve_mineru_cli()
MINERU_TOKEN_FILE = _resolve_mineru_token_file()

# 安全写入：备份保留份数；备份一律放【库外】，避免在 Obsidian 图谱里产生重复节点
BACKUP_DIR_NAME = "_备份"  # 仅用于兜底（未设置书目录时）
BACKUP_KEEP = 5
BACKUP_HOME = Path.home() / "obsidian_backups" / "拆书"

_BOOK_BACKUP_ROOT: "Path | None" = None


def set_book_backup_root(book_id: str) -> None:
    """在确定书名文件夹后调用：本书的备份根目录 = ~/obsidian_backups/拆书/<书名>/"""
    global _BOOK_BACKUP_ROOT
    _BOOK_BACKUP_ROOT = BACKUP_HOME / book_id


def book_backup_root(path: Path) -> Path:
    return _BOOK_BACKUP_ROOT or (path.parent / BACKUP_DIR_NAME)


# ---------- 安全写入（借鉴 obsidian-vault-mcp：原子替换 + 自动备份） ----------

def prune_backups(backup_root: Path, keep: int = BACKUP_KEEP) -> None:
    """只保留最近 keep 份备份，更早的删除。"""
    try:
        dirs = sorted([p for p in backup_root.iterdir() if p.is_dir()])
    except OSError:
        return
    for old in dirs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def backup_if_exists(path: Path) -> None:
    """覆盖前先把旧文件复制到库外 ~/obsidian_backups/拆书/<书名>/<时间戳>/。"""
    if path.exists():
        backup_root = book_backup_root(path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest_dir = backup_root / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, dest_dir / path.name)
            prune_backups(backup_root)
        except OSError as exc:
            print(f"[警告] 备份 {path.name} 失败：{exc}")


def atomic_write(path: Path, text: str) -> None:
    """先写临时文件再原子替换，避免写到一半损坏笔记。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_if_exists(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    """源文件指纹，用于防止重复拆分/识别同一本书。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


# ---------- 说明：全走 MinerU 流程（本地文字层提取已下线：EPUB/Word 请先转 PDF） ----------


# ---------- OCR（扫描版 PDF） ----------

def parse_page_range(spec: str, total: int):
    """解析 '1-100' / '50' 之类的页码范围（从 1 开始）。"""
    if not spec:
        return list(range(total))
    parts = [p.strip() for p in str(spec).split("-")]
    try:
        if len(parts) == 1:
            start = end = int(parts[0])
        elif len(parts) == 2:
            start, end = int(parts[0]), int(parts[1])
        else:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"无法解析页码范围：{spec}（示例：1-100）") from exc
    start = max(1, start)
    end = min(total, end)
    if start > end:
        raise ValueError(f"页码范围无效：{spec}（本书共 {total} 页）")
    return list(range(start - 1, end))


# ---------- MinerU 云端识别（扫描版 PDF，公式转 LaTeX） ----------

def find_mineru_cli(cli_arg: str) -> str:
    """定位 mineru-open-api 可执行文件。"""
    candidates = [
        cli_arg,
        os.environ.get("AIWF_MINERU_CLI", ""),
        os.environ.get("MINERU_CLI_COMMAND", ""),
        MINERU_DEFAULT_CLI,
        "mineru-open-api",
    ]
    for c in candidates:
        if not c:
            continue
        if Path(c).is_file() or shutil.which(c):
            return c
    raise RuntimeError(
        "找不到 MinerU 命令行工具。\n"
        "请先运行安装脚本创建虚拟环境（_工具/.venv），\n"
        "或用 --mineru-cli 指定 mineru-open-api 的完整路径。"
    )


def get_mineru_token(token_arg: str) -> str:
    """Token 优先级：命令行参数 > 环境变量 > 本库 _工具/mineru_token.txt。"""
    token = (
        token_arg
        or os.environ.get("MINERU_TOKEN")
        or os.environ.get("MINERU_API_TOKEN")
        or ""
    ).strip()
    if not token and MINERU_TOKEN_FILE.exists():
        token = MINERU_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(
            "缺少 MinerU Token。\n"
            "1) 去 https://mineru.net 免费注册，在「API管理 → Token」复制；\n"
            "2) 运行 _工具/设置MinerU令牌.bat 保存，\n"
            "   或加参数 --mineru-token <token>，或设置环境变量 MINERU_TOKEN。"
        )
    return token


# ---------- MinerU 上传分块（页数 + 体积双上限） ----------

MINERU_MAX_PAGES = 600  # MinerU 单文件页数硬上限
MINERU_MAX_MB = 200  # MinerU 单文件体积硬上限

# 上传阶段超时的特征（mineru-open-api 是 Go 写的，HTTP 客户端有固定超时，
# 100MB+ 的扫描件在 1-2 MB/s 的上行带宽下必挂：context deadline exceeded）
TIMEOUT_MARKERS = (
    "context deadline exceeded",
    "client.timeout exceeded",
    "timeout awaiting response headers",
    "tls handshake timeout",
    "i/o timeout",
    "connection reset by peer",
)


class MineruAuthError(RuntimeError):
    """Token 无效 / 当日额度受限（重试没有意义）。"""


class MineruUploadTimeout(RuntimeError):
    """上传超时：把这一份切小再传通常就能成功。"""


def _find_gs() -> str:
    """找 Ghostscript（用于把超大扫描件降采样，减小上传体积）。"""
    for name in ("gs", "gsc", "gswin64c", "gswin32c", "gs-noX11"):
        found = shutil.which(name)
        if found:
            return found
    return ""


MINERU_CACHE_KEEP = 6

# 已知书系的「每章固定收尾小节」预设（可选扩展点）：(书名关键词, 收尾小节正则, 章标题特征正则)
# 不命中也没关系：默认的 auto 会从正文自己挖（《某外语教材》已能自动识别，无需预设）
#   ("某外语教材", r"作业\s*\(Trabajos de casa", r"^\s*(?:#{1,6}\s*)?(?:[A-Za-z田\s]{0,8})?\b(?:UNIDAD|…)"),
END_ANCHOR_PRESETS = []


def _mineru_cache_path(src: Path, dpi: int) -> Path:
    """降采样结果的缓存路径（按文件名+大小+mtime+DPI 区分）。"""
    cache_dir = Path(__file__).resolve().parent / ".mineru_cache"
    st = src.stat()
    key = hashlib.md5(
        f"{src.name}|{st.st_size}|{int(st.st_mtime)}|{dpi}".encode("utf-8", "replace")
    ).hexdigest()[:12]
    safe = re.sub(r"[^\w.-]+", "_", src.stem)[:40]
    return cache_dir / f"{safe}-{key}.pdf"


def _prune_mineru_cache(cache_dir: Path) -> None:
    files = sorted(cache_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[MINERU_CACHE_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def compress_pdf_for_mineru(src: Path, dpi: int = 200) -> Path | None:
    """用 Ghostscript 把扫描图的分辨率降到 dpi（默认 200 DPI）。

    MinerU 的视觉模型本身会把页面缩到 ~1000px 长边，300 DPI 原图上传纯属浪费：
    200 MB / 305 页的书能压到 63 MB，识别质量看不出差别。
    结果缓存在 _工具/.mineru_cache/，同一本书重跑不压第二次。
    返回可直接用于分块上传的 PDF 路径（失败/收益不足返回 None）。
    """
    gs = _find_gs()
    if not gs or dpi <= 0:
        print("[MinerU] 没找到 Ghostscript，跳过降采样（上传可能较慢）")
        return None
    dst = _mineru_cache_path(src, dpi)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size > 0:
        print(
            f"[MinerU] 复用已有的 {dpi} DPI 缓存：{dst.name}"
            f"（{dst.stat().st_size/2**20:.1f} MB）"
        )
        _prune_mineru_cache(dst.parent)
        return dst
    cmd = [
        gs,
        "-q",
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        "-dPDFSETTINGS=/ebook",
        f"-dColorImageResolution={dpi}",
        f"-dGrayImageResolution={dpi}",
        "-dMonoImageResolution=600",
        "-dColorImageDownsampleThreshold=1.0",
        "-dGrayImageDownsampleThreshold=1.0",
        "-dMonoImageDownsampleThreshold=1.0",
        "-dDetectDuplicateImages=true",
        "-dAutoRotatePages=/None",
        f"-sOutputFile={dst}",
        str(src),
    ]
    print(f"[MinerU] 先用 Ghostscript 把扫描页降到 {dpi} DPI（几分钟，只降体积不降识别精度）...")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=7200)
    except Exception as exc:  # noqa: BLE001
        print(f"[MinerU] 降采样失败（{exc}），改用原文件上传")
        dst.unlink(missing_ok=True)
        return None
    detail = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0 or not dst.exists():
        print(f"[MinerU] 降采样失败（gs 退出码 {proc.returncode}），改用原文件上传")
        if detail:
            print(f"    {detail[:300]}")
        dst.unlink(missing_ok=True)
        return None
    before, after = src.stat().st_size, dst.stat().st_size
    if after >= before * 0.9:
        print(
            f"[MinerU] 降采样收益不足（{before/2**20:.1f} → {after/2**20:.1f} MB），改用原文件"
        )
        dst.unlink(missing_ok=True)
        return None
    print(
        f"[MinerU] 降采样完成：{before/2**20:.1f} MB → {after/2**20:.1f} MB"
        f"（{time.time() - t0:.0f} 秒，已缓存供重跑使用）"
    )
    _prune_mineru_cache(dst.parent)
    return dst


def _write_pdf_slice(reader, start: int, end: int, out: Path) -> int:
    """把第 start-end 页（1 起、含端点）写成一份 PDF，返回字节数。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for i in range(start - 1, end):
        writer.add_page(reader.pages[i])
    with out.open("wb") as fh:
        writer.write(fh)
    return out.stat().st_size


def pack_pdf_chunks(
    reader,
    start: int,
    end: int,
    chunk_pages: int,
    chunk_bytes: int,
    tmpdir: Path,
    tag: str = "part",
    acc: list | None = None,
):
    """把第 start-end 页切成若干份，同时满足页数与体积上限。

    单份超过 chunk_bytes 时对半再切（二分），保证每一份都能在
    mineru-open-api 的上传超时窗口内传完。返回 [(起页, 止页, 路径, 字节数)]。
    """
    acc = [] if acc is None else acc
    pages = max(1, min(chunk_pages, MINERU_MAX_PAGES, end - start + 1))
    lo = start
    while lo <= end:
        hi = min(lo + pages - 1, end)
        out = tmpdir / f"{tag}-{lo:04d}-{hi:04d}.pdf"
        size = _write_pdf_slice(reader, lo, hi, out)
        if chunk_bytes and size > chunk_bytes and hi > lo:
            mid = (lo + hi) // 2
            out.unlink(missing_ok=True)
            pack_pdf_chunks(reader, lo, mid, chunk_pages, chunk_bytes, tmpdir, tag, acc)
            lo = mid + 1
            continue
        if size > MINERU_MAX_MB * 1024 * 1024:
            print(
                f"    [警告] 第 {lo}-{hi} 页仍有 {size/2**20:.1f} MB，"
                "超过 MinerU 单文件 200MB 限制，可能上传失败"
            )
        acc.append((lo, hi, out, size))
        lo = hi + 1
    return acc


def split_pdf_for_mineru(
    src: Path, chunk_pages: int, tmpdir: Path, chunk_bytes: int = 0
):
    """把 PDF 按「≤chunk_pages 页且 ≤chunk_bytes」切成小文件。"""
    from pypdf import PdfReader

    reader = PdfReader(str(src))
    total = len(reader.pages)
    chunks = pack_pdf_chunks(reader, 1, total, chunk_pages, chunk_bytes, tmpdir)
    return chunks, total


def collect_markdown(out_dir: Path) -> str:
    """收集 MinerU 输出的 Markdown（full.md 或拆分出的多个 md）。"""
    mds = sorted(out_dir.rglob("*.md"))
    if not mds:
        raise RuntimeError(f"MinerU 没有产出 Markdown：{out_dir}")
    parts = []
    for md in mds:
        parts.append(md.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(parts)


def run_mineru_extract(
    cli: str,
    chunk: Path,
    out_dir: Path,
    token: str,
    language: str,
    model: str,
    timeout: int,
    max_attempts: int = 3,
) -> None:
    """调用 mineru-open-api extract 解析一份 PDF（自动上传/轮询/下载）。

    网络不稳定时自动重试最多 max_attempts 次；Token 无效/额度问题不重试；
    上传超时（文件太大/上行太慢）抛 MineruUploadTimeout，由调用方把这一份切小再传。
    """
    upload_timeout = False
    detail = ""
    for attempt in range(1, max_attempts + 1):
        cmd = [
            cli,
            "extract",
            str(chunk),
            "-o",
            str(out_dir),
            "-f",
            "md",
            "-l",
            language,
            "--ocr",
            "--model",
            model,
            "--token",
            token,
            "--timeout",
            str(timeout),
        ]
        print(
            f"    调用: {Path(cli).name} extract {chunk.name}"
            f"（第 {attempt}/{max_attempts} 次尝试）..."
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 60,
            )
            if proc.returncode == 0:
                return
            detail = (proc.stderr or proc.stdout or "无输出").strip()
        except subprocess.TimeoutExpired:
            detail = f"本地等待超过 {timeout + 60} 秒（任务可能还在云端排队）"
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"MinerU 启动失败：{exc}") from exc

        # 鉴权/额度类错误不重试
        if any(k in detail for k in ("401", "A0202", "user authenticate failed")):
            raise MineruAuthError(
                f"MinerU 解析失败（{chunk.name}）：Token 无效或当日额度受限\n{detail[:800]}"
            )
        low = detail.lower()
        upload_timeout = "upload" in low and any(m in low for m in TIMEOUT_MARKERS)
        if upload_timeout and attempt >= 2:
            break  # 同样大小再传也没用，交给上层切小
        if attempt < max_attempts:
            wait = 20 * attempt
            print(
                f"    第 {attempt} 次失败"
                f"{'（上传超时）' if upload_timeout else ''}，{wait} 秒后自动重试...\n"
                f"    原因摘要：{detail[:400]}"
            )
            time.sleep(wait)
            continue
        break

    if upload_timeout:
        raise MineruUploadTimeout(
            f"MinerU 上传超时（{chunk.name}，"
            f"{chunk.stat().st_size / 2**20:.1f} MB）：\n{detail[:600]}"
        )
    raise RuntimeError(f"MinerU 解析失败（{chunk.name}）：\n{detail[:1500]}"[:3000])


def mineru_ocr_pdf(
    path: Path,
    token: str,
    cli_arg: str,
    chunk_pages: int,
    language: str,
    model: str,
    dry_run: bool,
    images_target: Path | None = None,
    chunk_mb: int = 25,
    dpi: int = 200,
) -> str:
    """把扫描版 PDF 分块上传 MinerU 云端识别，返回带页码注释的全文。"""
    from pypdf import PdfReader

    cli = find_mineru_cli(cli_arg)
    token = get_mineru_token(token)
    cap_bytes = max(0, chunk_mb) * 1024 * 1024
    print(f"[MinerU] 工具：{cli}")
    print(
        f"[MinerU] 每日免费额度 1000 页，本任务按 {chunk_pages} 页/份"
        + (f"、≤{chunk_mb} MB/份" if cap_bytes else "")
        + "分块上传"
    )

    with tempfile.TemporaryDirectory(prefix="mineru_") as tmp:
        tmpdir = Path(tmp)
        src = path
        reader = PdfReader(str(src))
        total = len(reader.pages)
        # 扫描书常见：页数没超但单份几百 MB，上传必超时 —— 先降采样再分块
        if cap_bytes and dpi:
            per_page = src.stat().st_size / max(1, total)
            est = per_page * min(chunk_pages, MINERU_MAX_PAGES, total)
            if est > cap_bytes:
                print(
                    f"[MinerU] 平均每页 {per_page/2**20:.2f} MB，"
                    f"单份约 {est/2**20:.0f} MB，直接上传容易超时"
                )
                downscaled = compress_pdf_for_mineru(src, dpi)
                if downscaled is not None:
                    src = downscaled
                    reader = PdfReader(str(src))
                    total = len(reader.pages)
        chunks = pack_pdf_chunks(reader, 1, total, chunk_pages, cap_bytes, tmpdir)
        print(f"[MinerU] 全书 {total} 页 → {len(chunks)} 份：")
        for start, end, c, size in chunks:
            print(f"  - 第 {start}-{end} 页（{size / 2**20:.1f} MB）")
        if dry_run:
            print("[MinerU] 试运行模式：以上只是分块计划，未上传、未消耗额度。")
            return ""

        results: dict[int, str] = {}
        tasks = deque(chunks)
        parsed = 0
        while tasks:
            start, end, c, size = tasks.popleft()
            out_dir = tmpdir / f"out-{start:04d}-{end:04d}"
            print(
                f"[MinerU] 上传解析 原书第 {start}-{end} 页"
                f"（{size/2**20:.1f} MB，已完 {parsed}/{total} 页），"
                "约 2-8 分钟，请耐心等待..."
            )
            try:
                run_mineru_extract(
                    cli, c, out_dir, token, language, model, timeout=1800
                )
            except MineruUploadTimeout:
                if end - start < 1 or not cap_bytes:
                    raise
                new_cap = max(4 * 1024 * 1024, size // 2)
                print(
                    f"    上传超时 → 把第 {start}-{end} 页再切小"
                    f"（≤{new_cap/2**20:.0f} MB）重传..."
                )
                sub: list = []
                pack_pdf_chunks(
                    reader,
                    start,
                    end,
                    max(1, (end - start + 1) // 2),
                    new_cap,
                    tmpdir,
                    tag=f"retry{start:04d}",
                    acc=sub,
                )
                c.unlink(missing_ok=True)
                tasks.extendleft(reversed(sub))
                continue
            content = collect_markdown(out_dir)
            if images_target is not None:
                src_img = out_dir / "images"
                if src_img.is_dir():
                    dst_img = images_target / "images"
                    dst_img.mkdir(parents=True, exist_ok=True)
                    copied = 0
                    for f in src_img.iterdir():
                        if f.is_file() and not (dst_img / f.name).exists():
                            shutil.copy2(f, dst_img / f.name)
                            copied += 1
                    if copied:
                        print(f"    图片已保留：{copied} 张 → {dst_img}")
            results[start] = f"<!-- 原书第 {start}-{end} 页 -->\n\n{content}"
            parsed += end - start + 1
            print(f"    完成：{len(content):,} 字符")
        return "\n\n---\n\n".join(results[k] for k in sorted(results))


# ---------- 章节与分块 ----------

def split_chapters(text: str):
    """按常见章节标题切分；识别不到就整本作为一个章节。"""
    chapters = []
    current = []
    current_title = "全文"
    for line in text.splitlines():
        stripped = line.strip()
        normalized = re.sub(
            r"(第)\s*([0-9一二三四五六七八九十百千万零〇]+)\s*([章节卷篇部讲课])",
            r"\1\2\3",
            stripped,
        )
        m = CHAPTER_RE.match(normalized)
        if m and len(stripped) < 80:
            if current:
                chapters.append((current_title, "\n".join(current)))
            current_title = (m.group(1) or "").strip() or stripped
            current = [stripped]
        else:
            current.append(line)
    if current:
        chapters.append((current_title, "\n".join(current)))
    return [(t, b) for t, b in chapters if len(b) >= 30]


def split_chunks(text: str, max_chars: int, overlap: int):
    """把一段长文本按段落边界切成若干块。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    cur = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(para), max_chars - overlap):
                chunks.append(para[i : i + max_chars])
            continue
        if cur and len(cur) + len(para) + 2 > max_chars:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = tail + "\n\n" + para if tail else para
        else:
            cur = cur + "\n\n" + para if cur else para
    if cur:
        chunks.append(cur)
    return chunks


def safe_name(name: str, limit: int = 40) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "", name).strip()
    name = re.sub(r"\s+", " ", name)
    name = name[:limit] or "未命名"
    return name.rstrip(" .")


# ---------- 标题感知切分（准确识别章节） ----------

HEADING_LINE_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)
CHAPTER_LINE_RE = re.compile(
    r"^(?:" + CHAPTER_WORD_ANCHOR + r")\s*(\d+)\s*[:：.\-–—]?\s*(.+?)\s*(\d{1,4})?\s*$",
    re.I,
)
CN_CHAPTER_LINE_RE = re.compile(
    r"^第\s*([0-9一二三四五六七八九十百千万零〇]+)\s*章\s*[:：.\-–—]?\s*(.+?)\s*(\d{1,4})?\s*$"
)


def _norm_title(title: str) -> str:
    """标题归一化：小写、去空格和标点，用于匹配。"""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())


def _strip_page_no(title: str) -> str:
    """去掉标题末尾的页码，如 'The Goods Market 45' -> 'The Goods Market'。"""
    return re.sub(r"\s+\d{1,4}$", "", title).strip()


# ---------- 多锚点章节识别（通用引擎） ----------

# 书后区关键词（答案/附录/索引等），命中后其后的内容不再参与章节扫描
BACK_MATTER_KEYWORDS_EN = [
    "answers to selected odd-numbered questions",
    "answers to odd-numbered",
    "answers to selected exercises",
    "answers to exercises",
    "answers to review questions",
    "solutions to selected",
    "solutions to odd-numbered",
    "answers",
    "appendix",
    "appendices",
    "bibliography",
    "references",
    "index",
    "glossary",
]
BACK_MATTER_KEYWORDS_ZH = [
    "奇数号习题答案",
    "习题答案",
    "练习答案",
    "答案",
    "索引",
    "参考文献",
    "词汇表",
    "附表",
    "术语表",
    "译后记",
    "译 后 记",
]
BACK_MATTER_KEYWORDS_ES = [
    "respuestas a las preguntas",
    "respuestas a los ejercicios",
    "soluciones a los ejercicios",
    "soluciones",
    "respuestas",
    "apéndice",
    "apendice",
    "apéndices",
    "apendices",
    "índice",
    "indice",
    "referencias",
    "bibliografía",
    "bibliografia",
    "glosario",
]
BACK_MATTER_KEYWORDS_IT = [
    "risposte alle domande",
    "risposte agli esercizi",
    "soluzioni degli esercizi",
    "soluzioni",
    "risposte",
    "appendice",
    "appendici",
    "indice",
    "riferimenti",
    "bibliografia",
    "glossario",
]

# 章首页小目录标记：CHAPTER OUTLINE 等（用于把章首页归属到本章）
CHAPTER_OUTLINE_RE = re.compile(
    r"^\s*(?:#{1,4}\s+)?(?:chapter\s+outline|chapter\s+contents|contents|"
    r"in\s+this\s+chapter|what\s+you.?ll\s+learn|"
    r"contenido|sumario|sommario|contenuto|"
    r"en\s+este\s+cap[íi]tulo|in\s+questo\s+capitolo|"
    r"本章目录|本章内容|目录)\s*$",
    re.I,
)

# 带 # 标记的正文小节标题：## 2.1 INTRODUCTION / ## 8-1 INFLATION...
# （MinerU 对正文标题通常加 #；小数点和连字符两种编号都支持）
MARKED_SECTION_RE = re.compile(
    r"^\s*#{1,4}\s+(\d{1,3})[.．\-](\d{1,3})(?:[.．\-]\d{1,3})?\b\s*(.*)$"
)
# 任意"数字编号开头"的行（用于识别密集的章首页小目录/习题列表）
PLAIN_NUM_RE = re.compile(
    r"^\s*(\d{1,3})[.．\-](\d{1,3})(?:[.．\-]\d{1,3})?\b\s*"
)

# 带 # 标记的正文章标题：## CHAPTER 2 / # Chapter 1 Title
MARKED_CHAPTER_RE = re.compile(
    r"^\s*#{1,4}\s+(?:" + CHAPTER_WORD_ANCHOR + r")\s*(\d+)\b\s*(.*)$", re.I
)
# 无标记的章标题（用于排除，不作为锚点）：CHAPTER 5 等
PLAIN_CHAPTER_RE = re.compile(
    r"^\s*(?:" + CHAPTER_WORD_ANCHOR + r")\s*(\d+)\b\s*(.*)$", re.I
)
# 中文"第N章"，带或不带 # 标记
MARKED_CN_CHAPTER_RE = re.compile(
    r"^\s*#{1,4}\s*第\s*([0-9一二三四五六七八九十百千万零〇]+)\s*章\s*[:：.\-–—]?\s*(.*)$"
)

# 意大利语序数词章节标题：Prima lezione / Seconda lezione / Lezione prima ...
# （MinerU 常把这类标题识别为 "# Seconda lezione" 或目录里的 "Prima lezione....(1)"）
IT_ORDINALS = {
    "prima": 1, "seconda": 2, "terza": 3, "quarta": 4, "quinta": 5,
    "sesta": 6, "settima": 7, "ottava": 8, "nona": 9, "decima": 10,
    "undicesima": 11, "dodicesima": 12, "tredicesima": 13, "quattordicesima": 14,
    "quindicesima": 15, "sedicesima": 16, "diciassettesima": 17, "diciottesima": 18,
    "diciannovesima": 19, "ventesima": 20, "ventunesima": 21, "ventiduesima": 22,
    "ventitreesima": 23, "ventiquattresima": 24, "venticinquesima": 25,
    "ventiseiesima": 26, "ventisettesima": 27, "ventottesima": 28,
    "ventinovesima": 29, "trentesima": 30,
}
_IT_ORD_ALT = "|".join(IT_ORDINALS)
_IT_ORD_NOUN = (
    r"(?:lezione|lezion[èé]|unità|unita|parte|capitolo|capitulo|sezione|modulo|"
    r"secci[óo]n|lecci[óo]n|unidad)"
)
# 带 # 标记（正文标题）：# Prima lezione / ## Lezione seconda（两种语序）
MARKED_IT_ORDINAL_RE = re.compile(
    r"^\s*#{1,4}\s*(?:(" + _IT_ORD_ALT + r")\s+" + _IT_ORD_NOUN +
    r"|" + _IT_ORD_NOUN + r"\s+(" + _IT_ORD_ALT + r"))\s*(.*)$",
    re.I,
)
# 无标记（目录条目/纯文本标题）
PLAIN_IT_ORDINAL_RE = re.compile(
    r"^\s*(?:(" + _IT_ORD_ALT + r")\s+" + _IT_ORD_NOUN +
    r"|" + _IT_ORD_NOUN + r"\s+(" + _IT_ORD_ALT + r"))\s*(.*)$",
    re.I,
)


def _it_ordinal_from_match(m) -> int | None:
    """从序数词匹配里取章号：Prima lezione / Lezione prima 两种语序都支持。"""
    return IT_ORDINALS.get(((m.group(1) or m.group(2)) or "").strip().lower())


def obsidian_img_links(text: str) -> str:
    """把 MinerU 的 Markdown 图片链接 ![](images/xxx.jpg) 转为
    Obsidian 维基嵌入 ![[xxx.jpg]]：按文件名全库解析，任意目录深度都能显示，
    不受书文件夹名里的括号/逗号等特殊字符影响。"""
    return re.sub(
        r"!\[\]\(images/([^)\s]+\.(?:png|jpe?g|gif|webp|bmp|svg))\)",
        r"![[\1]]",
        text,
        flags=re.I,
    )

# 目录条目引导点（……/.../···）
LEADER_DOTS_RE = re.compile(r"[.…·]{2,}")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_to_int(s: str):
    """中文/阿拉伯数字章节号统一转 int；无法解析返回 None。"""
    s = str(s).strip()
    if s.isdigit():
        return int(s)
    if not s or any(c not in "零〇一二三四五六七八九十百千万两" for c in s):
        return None
    if "百" in s or "千" in s:
        # 仅处理 1-999 的常见写法
        unit = "百" if "百" in s else "千"
        head, _, tail = s.partition(unit)
        base = _CN_DIGITS.get(head, 0) or 1
        base *= 100 if unit == "百" else 1000
        return base + (_cn_to_int(tail) if tail else 0)
    if "十" not in s:
        return sum(_CN_DIGITS.get(c, 0) for c in s)
    total = 0
    if s.startswith("十"):
        total += 10
        s = s[1:]
    elif "十" in s:
        head, _, tail = s.partition("十")
        total += (_CN_DIGITS.get(head, 0) if head else 0) * 10
        s = tail
    if s:
        total += _CN_DIGITS.get(s, 0) if len(s) == 1 else sum(
            _CN_DIGITS.get(c, 0) for c in s
        )
    return total or None


def _clean_toc_title(raw: str) -> str:
    """清洗目录条目标题：去掉引导点（……）及其后的页码、多余标点。"""
    t = (raw or "").strip()
    t = LEADER_DOTS_RE.split(t)[0]
    t = re.sub(r"\s+\d{1,4}\s*$", "", t)
    t = t.strip(" \t.:：-–—·…")
    t = re.sub(r"\s+", " ", t)
    return t


def _clean_anchor_title(raw: str) -> str:
    """清洗正文锚点标题：去掉 # 标记与首尾标点。"""
    t = re.sub(r"^#{1,6}\s*", "", (raw or "").strip())
    t = re.sub(r"\s+", " ", t).strip(" \t.:：-–—·…")
    return t


def _toc_entry(s: str):
    """从一行里解析目录条目。仅当明显像目录行（引导点或尾随页码）才接受。

    返回 (num:int, title:str) 或 None。正文标题（无引导点/页码）不算目录。
    """
    s = s.strip()
    if not s or len(s) > 130:
        return None
    has_dots = bool(LEADER_DOTS_RE.search(s))
    has_page = bool(re.search(r"\s\d{1,4}\s*$", s))
    if not (has_dots or has_page):
        return None
    num_raw = title_raw = None
    m = CHAPTER_LINE_RE.search(s)
    if m:
        num_raw, title_raw = m.group(1), (m.group(2) or "")
    else:
        m2 = CN_CHAPTER_LINE_RE.search(s)
        if m2:
            num_raw, title_raw = m2.group(1), (m2.group(2) or "")
        elif has_dots:
            m3 = re.match(r"^\s*(\d{1,2})\s+(.+?)\s*$", s)
            if m3:
                num_raw, title_raw = m3.group(1), m3.group(2)
        m4 = PLAIN_IT_ORDINAL_RE.match(s)
        if m4:
            num = _it_ordinal_from_match(m4)
            if num is not None:
                title = _clean_toc_title(re.sub(r"^\s*#{1,6}\s*", "", s).strip())
                if title and len(title) >= 2 and len(title) <= 100:
                    return num, title
    if num_raw is None:
        return None
    num = _cn_to_int(num_raw)
    if num is None:
        return None
    title = _clean_toc_title(title_raw)
    if not title or len(title) < 2 or len(title) > 100:
        return None
    return num, title


def _extract_toc(lines, scan_end: int) -> dict:
    """从前 1/4 区域提取"章号 -> 标题"名单（优先保留最长标题）。"""
    toc = {}
    region = min(scan_end, max(60, int(len(lines) * 0.25)))
    for ln in lines[:region]:
        m = _toc_entry(ln)
        if not m:
            continue
        num, title = m
        if num not in toc or len(title) > len(toc[num]):
            toc[num] = title
    return toc


def _is_back_matter_line(s: str, strict: bool) -> bool:
    """判断一行是否像书后区（答案/附录/索引等）的大标题。"""
    s = s.strip()
    if not s or len(s) > 80:
        return False
    if re.search(r"\d", s):  # 带数字的行（N.M 小节/附录编号/表格名）不算
        return False
    if MARKED_SECTION_RE.match(s) or PLAIN_CHAPTER_RE.match(s) or CN_CHAPTER_LINE_RE.match(s):
        return False
    core = re.sub(r"^#{1,6}\s*", "", s).strip()
    low = core.lower()

    def _kw_hit(low, kw):
        """关键词整词/前缀命中：避免 'indexed' 误命中 'index'。"""
        if low == kw:
            return True
        return low.startswith(kw + " ") or low.startswith(kw + ":") or low.startswith(
            kw + "："
        )

    if any(_kw_hit(low, k) for k in BACK_MATTER_KEYWORDS_ZH):
        return True
    if any(_kw_hit(low, k) for k in BACK_MATTER_KEYWORDS_ES) or any(
        _kw_hit(low, k) for k in BACK_MATTER_KEYWORDS_IT
    ):
        return True
    if strict and not core.isupper():
        return False
    if (
        not strict
        and not core.isupper()
        and not s.startswith("#")
        and len(core) > 50
    ):
        return False
    return any(_kw_hit(low, k) for k in BACK_MATTER_KEYWORDS_EN)


def _find_back_matter_cutoff(lines):
    """书后区截断：返回第一个书后标记的行号；没找到返回 None。

    >40%：全大写英文/中文关键词（章内长附录不误伤）；
    >75%：允许大小写的短标题/短文本；
    >65%：带 # 的短标题（如 "## Index" / "## Glossary"）也认可。
    """
    total = len(lines)
    for i in range(int(total * 0.40), total):
        s = lines[i].strip()
        if not s or len(s) > 80:
            continue
        strict = i < int(total * 0.75)
        if _is_back_matter_line(s, strict=strict):
            return i
    for i in range(int(total * 0.65), total):
        s = lines[i].strip()
        if not s or len(s) > 80 or not s.startswith("#"):
            continue
        core = re.sub(r"^#{1,6}\s*", "", s).strip()
        if len(core) > 40 or ":" in core:
            continue
        if _is_back_matter_line(s, strict=False):
            return i
    return None


def _in_dense_cluster(lines, i: int, scan_end: int) -> bool:
    """判断第 i 行是否属于"连续编号行簇"（章首页小目录/习题列表），而非正文标题。

    正文标题是"稀疏"的（后面跟大段正文）；小目录是"密集"的
    （后面紧跟 2 个以上短编号行、且没有长段落）。
    """
    nxt = []
    j = i + 1
    while j < scan_end and len(nxt) < 4:
        s = lines[j].strip()
        if s:
            nxt.append(s)
        j += 1
    if not nxt:
        return False
    num_like = 0
    for s in nxt:
        if MARKED_SECTION_RE.match(s) or PLAIN_NUM_RE.match(s):
            num_like += 1
        elif len(s) > 100:
            return False
    return num_like >= 2


def _in_dense_chapter_cluster(lines, i: int, scan_end: int) -> bool:
    """判断第 i 行是否属于"目录区连续章条目"（Contents 里 Chapter N 一行接一行）。"""
    nxt = []
    j = i + 1
    while j < scan_end and len(nxt) < 3:
        s = lines[j].strip()
        if s:
            nxt.append(s)
        j += 1
    if not nxt:
        return False
    chap_like = 0
    for s in nxt:
        core = re.sub(r"^#{1,4}\s*", "", s)
        if (
            MARKED_CHAPTER_RE.match(s)
            or MARKED_CN_CHAPTER_RE.match(s)
            or MARKED_IT_ORDINAL_RE.match(s)
            or PLAIN_CHAPTER_RE.match(core)
            or CN_CHAPTER_LINE_RE.match(core)
            or PLAIN_IT_ORDINAL_RE.match(core)
        ):
            chap_like += 1
        elif len(s) > 100:
            return False
    return chap_like >= 2


def _collect_anchors(lines, scan_end: int):
    """收集每章候选锚点：chapter（正文章标题行）与 section（正文小节标题行）。

    只认带 # 标记的标题行（正文标题特征），排除 HTML 表格/图片行；
    章首页小目录里的纯文本编号行天然不匹配，密集编号簇再过滤一道；
    目录页条目（带页码或连续成簇的 Chapter N）不作为正文锚点。
    额外收集目录区之后的"纯章名标题"（如 `# A Tour of the World`），
    供与目录章名比对，处理"Chapter N 标题缺失、N-1 小节也未识别"的书。

    返回 (anchors: dict, titles: list[(line, text)])
    """
    anchors = {}
    titles = []
    front_limit = max(60, int(scan_end * 0.35))
    for i in range(scan_end):
        s = lines[i].strip()
        if not s or s.startswith(("<", "![")):
            continue
        m = MARKED_CHAPTER_RE.match(s)
        if m:
            num = _cn_to_int(m.group(1))
            if num is not None:
                toc_like = bool(re.search(r"\s\d{1,4}\s*$", s))
                if not toc_like and not _in_dense_chapter_cluster(
                    lines, i, scan_end
                ):
                    title = (m.group(2) or "").strip()
                    if not title and i + 1 < scan_end:
                        nxt = lines[i + 1].strip()
                        if (
                            nxt
                            and len(nxt) < 110
                            and not re.match(
                                r"^(?:chapter|chap\.?|第|#{1,4}\s|!\[|<)",
                                nxt,
                                re.I,
                            )
                        ):
                            title = nxt
                    anchors.setdefault(num, []).append(("chapter", i, title))
            continue
        m2 = MARKED_CN_CHAPTER_RE.match(s)
        if m2:
            num = _cn_to_int(m2.group(1))
            if num is not None:
                toc_like = bool(re.search(r"\s\d{1,4}\s*$", s))
                if not toc_like and not _in_dense_chapter_cluster(
                    lines, i, scan_end
                ):
                    title = (m2.group(2) or "").strip()
                    anchors.setdefault(num, []).append(("chapter", i, title))
            continue
        m2b = MARKED_IT_ORDINAL_RE.match(s)
        if m2b:
            num = _it_ordinal_from_match(m2b)
            if num is not None:
                toc_like = bool(re.search(r"\s\d{1,4}\s*$", s))
                if not toc_like and not _in_dense_chapter_cluster(
                    lines, i, scan_end
                ):
                    title = re.sub(r"^#{1,6}\s*", "", s).strip()
                    anchors.setdefault(num, []).append(("chapter", i, title))
            continue
        m3 = MARKED_SECTION_RE.match(s)
        if m3:
            num = _cn_to_int(m3.group(1))
            if num is not None:
                toc_like = bool(re.search(r"\s\d{1,4}\s*$", s))
                in_front = i < front_limit
                if (
                    (not toc_like or not in_front)
                    and not _in_dense_cluster(lines, i, scan_end)
                ):
                    anchors.setdefault(num, []).append(("section", i, ""))
            continue
        # 纯章名标题候选：不带页码的 # 标题行（后续与目录章名精确比对）
        toc_like = bool(
            re.search(r"\s\d{1,4}\s*$", s)
            or re.search(r"\(\s*\d{1,4}\s*\)\s*$", s)  # 目录页码 (1) 格式
        )
        if s.startswith("#") and not toc_like:
            title = re.sub(r"^#{1,6}\s*", "", s).strip()
            if title and len(title) <= 80:
                titles.append((i, title))
    return anchors, titles


def _backtrack_opener(lines, start_line: int, prev_line: int, scan_end: int):
    """从某章第一个小节标题向前找章首页标记（CHAPTER OUTLINE 等），
    把章首页（含小目录）归属到本章，而不是粘在上一章末尾。"""
    win = 100
    lo = max(prev_line + 1, start_line - win)
    for i in range(start_line - 1, lo - 1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if CHAPTER_OUTLINE_RE.match(s):
            return i
        # 遇到前一章的标题/小节标题就停，绝不越过
        if (
            MARKED_SECTION_RE.match(s)
            or MARKED_CHAPTER_RE.match(s)
            or MARKED_CN_CHAPTER_RE.match(s)
            or MARKED_IT_ORDINAL_RE.match(s)
        ):
            return None
    return None


# 标题前缀（去噪用）：正文章标题常带「第N章 / N / N. / N、」前缀（MinerU 有时只认出编号）
_HEAD_PREFIX_RE = re.compile(
    r"^(?:第\s*[0-9零〇一二三四五六七八九十百千万]+\s*[章节篇部讲课]"
    r"|chapter\s*[0-9零〇一二三四五六七八九十]+"
    r"|[0-9]{1,3}\s*[.、．]?\s*)",
    re.I,
)


def _head_core(title: str) -> str:
    """标题归一 + 去掉「第N章 / N / N.」编号前缀，用于目录名↔正文标题比对。"""
    t = (title or "").strip()
    t = _HEAD_PREFIX_RE.sub("", t, count=1)
    return _norm_title(t)


def _find_title_anchor(titles, tn: str, prev_line: int):
    """在正文纯标题行中找与目录章名匹配的一行，返回行号或 None。

    比对先整体精确，再「去编号前缀后精确/双向前缀」：
    正文标题常是「# 4 货币系统：…」（多个编号）或「# 开放的经济」（丢了「第N章」），
    与目录名「货币系统：…」只有前缀之差。候选必须在该章第一个锚点之后（prev_line）。"""
    tn_norm = _norm_title(tn)
    if not tn_norm or len(tn_norm) < 2:
        return None
    cands = [(i, t) for i, t in titles if i > prev_line]
    exact = [i for i, t in cands if _norm_title(t) == tn_norm]
    if exact:
        return exact[-1]
    # 去编号前缀后比对：正文「13 重访开放经济: …」↔ 目录「重访开放经济：…」
    loose = [
        (i, _head_core(t))
        for i, t in cands
        if _head_core(t) and _head_core(t) == tn_norm
    ]
    if loose:
        return loose[-1][0]
    if len(tn_norm) >= 8:
        pref = [
            (i, _head_core(t))
            for i, t in cands
            if _head_core(t)
            and (
                _head_core(t).startswith(tn_norm)
                or (len(_head_core(t)) >= 8 and tn_norm.startswith(_head_core(t)))
            )
        ]
        if pref:
            return pref[-1][0]
    return None


def _build_bounds(toc, anchors, titles, lines, offsets, scan_end: int, opener_re=None) -> list:
    """按章号把"锚点 + 目录名单"合成正文起点，返回 [(num, title, char_pos), ...]。"""
    nums = sorted(set(toc) | set(anchors))
    anchor_map = {}
    prev_anchor_line = -1
    for num in nums:
        entries = anchors.get(num, [])
        chap = [e for e in entries if e[0] == "chapter"]
        sec = [e for e in entries if e[0] == "section"]
        anchor_line = None
        if chap:
            anchor_line = chap[-1][1]
        else:
            sec_first = sec[0][1] if sec else None
            title_anchor = _find_title_anchor(
                titles, toc.get(num, ""), prev_anchor_line
            )
            # 真实章标题一定在该章第一个小节之前；标题锚点晚于小节则视为误匹配
            if title_anchor is not None and (
                sec_first is None or title_anchor < sec_first
            ):
                anchor_line = title_anchor
            elif sec_first is not None:
                anchor_line = sec_first
                back = _backtrack_opener(lines, anchor_line, prev_anchor_line, scan_end)
                if back is not None and back > prev_anchor_line:
                    anchor_line = back
        if anchor_line is None or anchor_line <= prev_anchor_line:
            # 顺序异常：跳过该章（记入缺失），绝不硬造连续行
            continue
        anchor_map[num] = anchor_line
        prev_anchor_line = anchor_line

    # 回退：正文缺失章节标题（OCR 未识别）时，用"每章都有的开场标志"补齐，
    # 如 "--opener-pattern 'Impariamo a parlare'"。数量校验：相邻已知章节之间，
    # 开场行数必须恰好 = 缺失章数 + 1（多出的第一行属于上一章自己的开场），
    # 校验不过则放弃，绝不硬造分界。
    if opener_re:
        known = [n for n in nums if n in anchor_map]
        # 先补"开头缺失章"（第一已知章之前）：开场行数 == 缺失章数
        if known:
            first_k = known[0]
            hi = anchor_map[first_k]
            lead_missing = [
                n for n in nums
                if n < first_k and n not in anchor_map and toc.get(n)
            ]
            if lead_missing:
                openers = [
                    i for i in range(0, hi)
                    if lines[i].lstrip().startswith("#") and opener_re.search(lines[i])
                ]
                if len(openers) == len(lead_missing):
                    for k, mn in enumerate(sorted(lead_missing)):
                        anchor_map[mn] = openers[k]
                        known.append(mn)
        # 再补"中间缺失章"（相邻已知章之间）
        for num in nums:
            if num in anchor_map:
                continue
            prev_k = max((n for n in known if n < num), default=None)
            next_k = min((n for n in known if n > num), default=None)
            if prev_k is None and next_k is None:
                continue
            lo = anchor_map[prev_k] if prev_k is not None else -1
            hi = anchor_map[next_k] if next_k is not None else scan_end
            lo_num = prev_k if prev_k is not None else -1
            hi_num = next_k if next_k is not None else 10**9
            missing = [
                n for n in nums
                if lo_num < n < hi_num and n not in anchor_map and toc.get(n)
            ]
            openers = [
                i for i in range(lo + 1, hi)
                if lines[i].lstrip().startswith("#") and opener_re.search(lines[i])
            ]
            if len(openers) != len(missing) + 1:
                continue
            for k, mn in enumerate(sorted(missing)):
                anchor_map[mn] = openers[k + 1]
                known.append(mn)

    bounds = []
    prev_anchor_line = -1
    for num in nums:
        anchor_line = anchor_map.get(num)
        if anchor_line is None or anchor_line <= prev_anchor_line:
            continue
        title = toc.get(num)
        if not title:
            for _kind, _i, t in anchors.get(num, []):
                t2 = _clean_anchor_title(t)
                if t2:
                    title = t2
                    break
        if not title:
            title = f"第 {num} 章"
        bounds.append((num, title, offsets[anchor_line]))
        prev_anchor_line = anchor_line
    return bounds


def build_chapter_plan(text: str, opener_pattern: str = ""):
    """多锚点章节识别引擎。

    处理三类疑难：① 章节标题用特殊字体、MinerU 未识别 → 用小节编号/章首页标记定位；
    ② 书后答案/附录区重复出现同类标题 → 扫描前硬截断；
    ③ 章首页小目录（CHAPTER OUTLINE 列表）被识别为正文 → 密集编号簇过滤 + 起点回溯。

    返回 {"bounds": [(num, title, char_pos), ...], "toc_count", "missing", "back_matter"}
    或 None（识别不到）。
    """
    lines = text.split("\n")
    offsets = []
    off = 0
    for ln in lines:
        offsets.append(off)
        off += len(ln) + 1

    cutoff = _find_back_matter_cutoff(lines)
    scan_end = cutoff if cutoff is not None else len(lines)
    toc = _extract_toc(lines, scan_end)
    anchors, titles = _collect_anchors(lines, scan_end)
    opener_re = None
    if opener_pattern:
        try:
            opener_re = re.compile(opener_pattern, re.I)
        except re.error:
            print("[提示] --opener-pattern 不是有效正则，已忽略。")
    bounds = _build_bounds(toc, anchors, titles, lines, offsets, scan_end, opener_re)
    if len(bounds) < 2:
        return None
    bounds.sort(key=lambda b: b[2])
    missing = sorted(set(toc) - {b[0] for b in bounds})
    back_matter = None
    if cutoff is not None and cutoff < len(lines) - 2:
        tail = "\n".join(lines[cutoff:]).strip()
        if len(tail) > 50:
            title = _clean_anchor_title(lines[cutoff]) or "书后部分（答案/附录）"
            back_matter = (offsets[cutoff], title)
    return {
        "bounds": bounds,
        "toc_count": len(toc),
        "missing": missing,
        "back_matter": back_matter,
    }


def _int_to_cn(n: int) -> str:
    """1-99 → 中文数字（用来把章号还原成「第十课」这类书名里的写法）。"""
    digits = "零一二三四五六七八九"
    if not isinstance(n, int) or n < 0 or n > 99:
        return str(n)
    if n < 10:
        return digits[n]
    tens, ones = divmod(n, 10)
    s = "十" if tens == 1 else digits[tens] + "十"
    return s + (digits[ones] if ones else "")


def _unit_number(title: str):
    """从标题里抽章号：UNIDAD 8 / UNIDAD8 / 第八课 / 第8课 都能认。"""
    t = title or ""
    for pat in (r"unidad\s*([0-9]{1,3})", r"第\s*([0-9]{1,3})\s*课", r"([0-9]{1,3})\s*课"):
        m = re.search(pat, t, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"第\s*([零〇一二三四五六七八九十百]{1,4})\s*课", t)
    if m:
        return _cn_to_int(m.group(1))
    return None


def _line_offsets(lines) -> list:
    offs, off = [], 0
    for ln in lines:
        offs.append(off)
        off += len(ln) + 1
    return offs


CN_NUM = r"[0-9零〇一二三四五六七八九十百两]+"

# 看着就像「章名」的行（中西英意都认）：章标题被当成正文行输出时靠这个兑回
CHAPTERISH_RE = re.compile(
    r"(?:\b(?:unidad|unidade|chapter|cap[íi]tulo|capitolo|lesson|lecci[óo]n|"
    r"unit|parte|part|module|m[óo]dulo|sezione|lezione)\b"
    rf"|第\s*{CN_NUM}\s*[课章节讲]"
    rf"|第\s*{CN_NUM}\s*单元)",
    re.I,
)


def _norm_heading(s: str) -> str:
    """把标题行归一化成「小节名」：去 # 标记、编号前缀、图片、圈号，词序无关。

    中西双语书的同一小节会被识成「课文 TEXTOS」或「TEXTOS 课文」，
    按词排序归一后两者是同一个名字，统计频率才不会漏。
    """
    t = re.sub(r"^#{1,6}\s*", "", (s or "").strip())
    t = re.sub(r"<img[^>]*>", " ", t, flags=re.I)
    t = re.sub(r"[①-⑳▢□●○■◆▲△\u4e00\u7530]", " ", t)  # 装饰字母等 OCR 垃圾
    t = re.sub(r"^(?:[IVXLCDM]{1,7}|[0-9]{1,3})\s*[.、．:：]\s*", "", t, flags=re.I)
    words = sorted(w for w in re.split(r"[^0-9A-Za-z\u4e00-\u9fffÀ-ÿ]+", t) if w)
    return "|".join(words)[:36].upper()


def _looks_like_chapter_title(t: str) -> bool:
    return bool(t) and len(t) <= 60 and bool(CHAPTERISH_RE.search(t))


def _chapter_label(raws) -> str:
    """从各章标题里抽出章量词（UNIDAD / Chapter / …），抽不到返回空串。"""
    seen = {}
    for t in raws:
        if not _looks_like_chapter_title(t):
            continue
        m = re.search(r"[A-Za-zÀ-ÿ]{3,12}", t)
        if m:
            w = m.group(0)
            seen[w] = seen.get(w, 0) + 1
    return max(seen, key=lambda w: seen[w]) if seen else ""


def _plan_from_starts(text: str, starts, back_line):
    """由「各章起点行号 + 书后部分起点行号」生成与 build_chapter_plan 同构的计划。"""
    lines = text.split("\n")
    offsets = _line_offsets(lines)
    raw = [_clean_anchor_title(lines[i]) for i in starts]
    nums = [_unit_number(t) for t in raw]
    ok = (
        all(n is not None for n in nums)
        and nums == sorted(nums)
        and len(set(nums)) == len(nums)
    )
    label = _chapter_label(raw)
    cn_lesson = any(re.search(rf"第\s*{CN_NUM}\s*课", t) for t in raw)
    if not label and cn_lesson:
        label = "UNIDAD"
    bounds = []
    for seq, (line_idx, t) in enumerate(zip(starts, raw), start=1):
        num = nums[seq - 1] if ok and nums[seq - 1] else seq
        if label:
            title = f"{label} {num}" + (f" 第{_int_to_cn(num)}课" if cn_lesson else "")
        else:
            title = t or f"{num}"
        bounds.append((num, title, offsets[line_idx]))

    back_matter = None
    if back_line is not None and back_line < len(lines) - 2:
        tail = "\n".join(lines[back_line:]).strip()
        if len(tail) > 50:
            back_matter = (
                offsets[back_line],
                _clean_anchor_title(lines[back_line]) or "书后部分（答案/附录）",
            )
    front_matter = None
    if bounds and bounds[0][2] > 1200:
        front_matter = (bounds[0][2], "书前部分（前言/目录/语音表）")

    end_pos = back_matter[0] if back_matter else len(text)
    for i, (num, title, pos) in enumerate(bounds):
        nxt = bounds[i + 1][2] if i + 1 < len(bounds) else end_pos
        if nxt - pos < 1200:
            print(
                f"[警告] {title} 只占 {nxt - pos} 字，章界可能有误，"
                "请核对收尾小节是否每章只出现一次"
            )
    return {
        "bounds": bounds,
        "toc_count": len(bounds),
        "missing": [],
        "back_matter": back_matter,
        "front_matter": front_matter,
    }


def build_chapter_plan_by_end_anchor(
    text: str, end_pattern: str, title_pattern: str = "", start_pattern: str = ""
):
    """按「每一章都以同一个固定小节收尾」定位章界。

    适用于章标题用了装饰字体、被 OCR 整批打掉的教材：
    如《某外语教材》16 个 UNIDAD 标题只认出 7 个，
    但每课末尾都有「作业 (Trabajos de casa)」，16 次一次不差。

    规则：每个收尾行之后的第一个章标题行（# 开头，或 --chapter-title-pattern 命中的行）
    就是下一章起点；最后一个收尾行之后的第一个标题即书后部分（总词汇表等）。
    返回与 build_chapter_plan 同构的 dict（可多一个 front_matter），识别不到返回 None。
    """
    try:
        end_re = re.compile(end_pattern, re.I)
        title_re = re.compile(title_pattern, re.I) if title_pattern else None
        start_re = (
            re.compile(start_pattern, re.I)
            if start_pattern
            else re.compile(r"^\s*#{1,6}\s*[^\n#]{0,12}(?:课文\s*)?TEXTOS", re.I)
        )
    except re.error as exc:
        print(f"[章界识别] 正则无效（{exc}），改用通用章节识别。")
        return None

    lines = text.split("\n")
    offsets = []
    off = 0
    for ln in lines:
        offsets.append(off)
        off += len(ln) + 1

    def is_heading(s: str) -> bool:
        return s.lstrip().startswith("#")

    def skipable(s: str) -> bool:
        return not s.strip() or s.lstrip().startswith(("<", "![", "|", "["))

    def next_unit_head(after: int, limit: int | None = None, prefer=None):
        """收尾行之后的下一个章起点行号。

        先用 prefer（--chapter-title-pattern 给的「章标题特征」），找不到的话
        才退而取窗口里第一个 # 标题（很多书章标题被 OCR 打掉，只剩第一个小节标题）。
        """
        stop = limit if limit is not None else len(lines)
        first_head = None
        for i in range(after + 1, stop):
            s = lines[i]
            if skipable(s):
                continue
            if prefer is not None and prefer.match(s):
                return i
            if first_head is None and is_heading(s):
                first_head = i
        return first_head

    anchors = [
        i for i, ln in enumerate(lines) if end_re.search(ln) and not skipable(ln)
    ]
    if len(anchors) < 2:
        print(
            f"[章界识别] 只找到 {len(anchors)} 个收尾锚点，不足以定位章界，改用通用章节识别。"
        )
        return None

    heads = [
        i
        for i, ln in enumerate(lines)
        if (is_heading(ln) or (title_re and title_re.match(ln))) and not skipable(ln)
    ]
    before = [i for i in heads if i < anchors[0] and start_re.search(lines[i])]
    start_first = before[0] if before else (heads[0] if heads and heads[0] < anchors[0] else None)
    if start_first is None:
        print("[章界识别] 没定位到第一章的起点，改用通用章节识别。")
        return None

    starts = [start_first]
    for k in range(len(anchors) - 1):
        nxt = next_unit_head(anchors[k], anchors[k + 1], title_re)
        if nxt is None:
            print(
                f"[章界识别] 第 {k + 1} 章的收尾行之后找不到章起点（窗口 {anchors[k]+1}-{anchors[k+1]+1}），已跳过"
            )
            continue
        if nxt <= starts[-1]:
            continue
        starts.append(nxt)
    back_line = next_unit_head(anchors[-1])

    plan = _plan_from_starts(text, starts, back_line)
    print(
        f"[章界识别] 收尾锚点 {len(anchors)} 个 → 定位到 {len(plan['bounds'])} 章"
        f"（第一章从行 {starts[0] + 1} 开始）"
    )
    return plan


ENUM_COLON_RE = re.compile(r"^(?:[IVXLCDM]{1,7}|[0-9]{1,3})\s*[.、．]\s*\S")


def _is_wide_head(s: str) -> bool:
    """统计「每章固定小节」用的宽口径：# 标题、章名行、带编号又以冒号结尾的小节行。

    「XIV. 作业 (Trabajos de casa):」这种每章最后一节常常没被识成 # 标题，
    但正因为它在每章最后，宽口径才能把它挑出来当收尾锚点。
    """
    t = s.strip()
    if t.startswith("#"):
        return True
    if len(t) <= 30 and CHAPTERISH_RE.search(t):
        return True
    return len(t) <= 60 and t.endswith((":", "：")) and bool(ENUM_COLON_RE.match(t))


def _is_narrow_head(s: str) -> bool:
    """定章界用的严口径：只认 # 标题和章名行，免得把作业里的题号当成新章开头。"""
    t = s.strip()
    if t.startswith("#"):
        return True
    return len(t) <= 30 and bool(CHAPTERISH_RE.search(t))


def discover_chapter_plan(text: str, min_units: int = 4, min_gap: int = 2500):
    """一行参数都不给，自己从正文里把章界挖出来。

    ① 宽口径统计小节标题（归一化后），只留「每章出现且只出现一次」的：
       相邻两次至少隔 min_gap 字，且间隔均匀（每章长度相近）；
    ② 章数 k = 能有两个以上小节共享的最大出现次数（真每章一节不止一种，次数都 = k）；
    ③ 其中在每章里位置最靠后的那个 = 收尾锚点（如「作业 (Trabajos de casa)」）；
    ④ 章起点 = 严口径标题里，各窗口开头最常见的那个小节名（如「课文 TEXTOS」），
       没有就取窗口里第一个严口径标题。
    返回与 build_chapter_plan 同构的 dict；挖不出来返回 None（交回通用识别）。
    """
    lines = text.split("\n")
    offsets = _line_offsets(lines)

    def skipable(s: str) -> bool:
        return not s.strip() or s.lstrip().startswith(("<", "![", "|", "["))

    wide = [i for i, ln in enumerate(lines) if _is_wide_head(ln) and not skipable(ln)]
    heads = [i for i, ln in enumerate(lines) if _is_narrow_head(ln) and not skipable(ln)]
    by_name: dict = {}
    for i in wide:
        key = _norm_heading(lines[i])
        if len(key) >= 2:
            by_name.setdefault(key, []).append(i)
    good: dict = {}
    for key, idxs in by_name.items():
        if len(idxs) < min_units:
            continue
        gaps = [offsets[idxs[j + 1]] - offsets[idxs[j]] for j in range(len(idxs) - 1)]
        mean = sum(gaps) / len(gaps)
        # 真「每章一次」的小节：间隔均匀（每章长度相近）且每段都够长；
        # 只重复了几次的习题标题往往堆在书后半部，间隔会明显不均。
        if min(gaps) >= max(min_gap, 0.45 * mean):
            good[key] = idxs
    if len(good) < 2:
        return None
    counts: dict = {}
    for idxs in good.values():
        counts[len(idxs)] = counts.get(len(idxs), 0) + 1
    # 章数 = 能有至少两个同名小节共享的出现次数里最大的那个
    # （真的每章一节不会只有一种，且次数等于章数）
    k = max((c for c, n in counts.items() if n >= 2), default=0)
    sigs = {key: idxs for key, idxs in good.items() if len(idxs) == k}
    if k < min_units or len(sigs) < 2:
        return None
    best_key, best_score = None, -1
    for key, idxs in sigs.items():
        score = sum(
            1 for j in range(k) if idxs[j] == max(v[j] for v in sigs.values())
        )
        if score > best_score:
            best_key, best_score = key, score
    if best_score < k * 0.6:
        return None
    anchor_idx = sigs[best_key]

    # 章起点特征：只看每个窗口开头 3 个（严口径）标题，要求通常就是第一个
    win_pos: dict = {}
    for j in range(len(anchor_idx) - 1):
        lo, hi = anchor_idx[j], anchor_idx[j + 1]
        firsts = [h for h in heads if lo < h < hi][:3]
        for n, h in enumerate(firsts):
            win_pos.setdefault(_norm_heading(lines[h]), []).append(n)
    windows = max(1, len(anchor_idx) - 1)
    start_names = {
        name
        for name, pos in win_pos.items()
        if len(pos) >= max(2, int(windows * 0.4))
        and (sorted(pos)[len(pos) // 2] <= 1 or len(pos) >= windows * 0.6)
    }
    print(
        f"[自动章界] 每章收尾小节：「{best_key}」{k} 次 → 全书 {k} 章"
        + (f"；章起点特征：{'、'.join(sorted(start_names))}" if start_names else "")
    )

    def window_start(lo: int, hi: int):
        cand = [h for h in heads if lo < h < hi]
        if not cand:
            return None
        looks = [
            h
            for h in cand[:10]
            if _norm_heading(lines[h]) in start_names
            or (len(lines[h].strip()) <= 40 and CHAPTERISH_RE.search(lines[h]))
        ]
        return looks[0] if looks else cand[0]

    pre = [h for h in heads if h < anchor_idx[0]]
    start_first = None
    for h in reversed(pre):
        if _norm_heading(lines[h]) in start_names:
            start_first = h
            break
    if start_first is not None:
        # 第一章的章名行常常就在它上面（如「## UNIDAD 第一课」），把起点抬过去
        above = [h for h in pre if h < start_first and CHAPTERISH_RE.search(lines[h])]
        if above and start_first - above[-1] <= 30:
            start_first = above[-1]
    else:
        start_first = window_start(0, anchor_idx[0])
    if start_first is None:
        return None

    starts = [start_first]
    for j in range(len(anchor_idx) - 1):
        nxt = window_start(anchor_idx[j], anchor_idx[j + 1])
        if nxt is None or nxt <= starts[-1]:
            continue
        starts.append(nxt)
    if len(starts) < 2:
        return None
    tail_head = [h for h in heads if h > anchor_idx[-1]]
    return _plan_from_starts(text, starts, tail_head[0] if tail_head else None)


def _strip_leading_heading(body: str, title: str) -> str:
    """去掉正文开头的章节标题行，避免文件里重复出现两次标题。"""
    m = HEADING_LINE_RE.match(body)
    if m and _norm_title(m.group(2).strip()) == _norm_title(title):
        return body[m.end():].lstrip("\n")
    return body


def split_sections(body: str, chapter_title: str):
    """按 ##/### 小节标题把一章切成小节；没有小节时整章一个。"""
    heads = list(HEADING_LINE_RE.finditer(body))
    t_norm = _norm_title(chapter_title)
    starts = []
    for m in heads:
        title = m.group(2).strip()
        if _norm_title(title) == t_norm:
            continue
        starts.append((m.start(), title))
    if not starts:
        return [(chapter_title, body)]
    units = []
    for i, (pos, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        units.append((title, _strip_leading_heading(body[pos:end], title)))
    return units


def make_outline(
    book_id: str,
    short_hash: str,
    book_name: str,
    units,
    chapter_files: dict,
    text: str,
    mode: str,
    src_name: str,
) -> str:
    """生成《全书目录大纲》：章节清单（含定位和分块链接）+ 可勾选的进度清单。

    units: [(num, title, body, pos), ...]；chapter_files: {单元序号: [分块文件名]}
    """
    mode_label = {
        "chapter": "章节",
        "section": "小节",
        "chars": "标题",
    }.get(mode, "单元")
    lines = [
        "---\n",
        "type: book-outline\n",
        f"book_id: {book_id}\n",
        f"source_hash: {short_hash}\n",
        "---\n\n",
        f"# 🗺️《{book_name}》全书大纲\n\n",
        f"> 由拆书工具按{mode_label}拆分生成（来源：`{src_name}`），"
        f"共 {len(units)} 个单元。学习进度直接在下方清单勾选，"
        "或让 Claudian 运行「/更新进度」自动更新。\n\n",
        "## 📋 章节清单\n\n",
        "| 序 | 章 | 标题 | 起始位置 | 对应分块 |\n",
        "| --- | ---: | --- | --- | --- |\n",
    ]
    for i, (num, title, body, _pos) in enumerate(units, start=1):
        files = chapter_files.get(i, [])
        links = "、".join(f"[[{f}]]" for f in files) or "—"
        num_cell = f"第 {num} 章" if num else "—"
        title_cell = (title or "—").replace("|", "\\|")
        pos_line = text.count("\n", 0, _pos) + 1 if _pos is not None else "—"
        lines.append(
            f"| {i} | {num_cell} | {title_cell} | 全文第 {pos_line} 行 | {links} |\n"
        )
    lines += [
        "\n## ✅ 学习进度（勾选即记录）\n\n",
    ]
    for i, (num, title, body, _pos) in enumerate(units, start=1):
        num_cell = f"第 {num} 章 " if num else ""
        title_cell = (title or "—").replace("|", "\\|")
        lines.append(f"- [ ] {num_cell}{title_cell}\n")
    lines += [
        "\n> 📊 进度：0 / ",
        str(len(units)),
        " 已勾选（勾选后把本文件给 Claudian，或运行「/更新进度」）。\n",
    ]
    return "".join(lines)


# ---------- 主流程 ----------

def process_file(src: Path, out_root: Path, max_chars: int, overlap: int, args):
    print(f"\n=== 处理: {src.name} ===")
    source_hash = sha256_file(src)
    short_hash = source_hash[:12]
    engine = "text"
    ocr_raw = None
    is_resplit = src.suffix.lower() == ".md"

    # 稳定 ID：重切分时沿用已有书文件夹名，避免生成重复文件夹
    if is_resplit and (src.parent / "00-教材信息.md").exists():
        base = src.parent.name
    else:
        base = safe_name(args.book_name or src.stem, 50)
    book_id = base
    if is_resplit:
        book_name = safe_name(base, 60)
    else:
        book_name = safe_name(args.book_name or src.stem, 60)
    book_dir = out_root / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    set_book_backup_root(book_id)

    if is_resplit:
        engine = "resplit"
        raw = src.read_text(encoding="utf-8", errors="replace")
        raw = re.sub(r"^---\r?\n.*?\r?\n---\r?\n", "", raw, flags=re.S)
        raw = re.sub(r"^#\s+[^\n]*解析全文[^\n]*\r?\n", "", raw, flags=re.M)
        text = raw
        total_chars = len(text)
        print("[重切分] 从已有解析全文重新按标题切分（不消耗 MinerU 额度）")
    elif args.ocr == "mineru":
        if src.suffix.lower() != ".pdf":
            print(
                "[跳过] 只支持 PDF（全走 MinerU 云端识别）：\n"
                "       EPUB / Word 请先转成 PDF；已有 00-MinerU解析全文.md 可直接重切分。"
            )
            return
        engine = "mineru"
        print(f"[MinerU] 用 MinerU 云端解析 {src.name}（公式转 LaTeX）...")
        ocr_raw = mineru_ocr_pdf(
            src,
            token=args.mineru_token,
            cli_arg=args.mineru_cli,
            chunk_pages=args.mineru_chunk_pages,
            language=args.mineru_language,
            model=args.mineru_model,
            dry_run=args.mineru_dry_run,
            chunk_mb=args.mineru_chunk_mb,
            dpi=args.mineru_dpi,
            images_target=None if args.no_keep_images else book_dir,
        )
        if args.mineru_dry_run:
            print("[试运行结束] 确认分块计划没问题后，去掉 --mineru-dry-run 正式执行。")
            return
        # 去掉页码注释标记，避免混入章节正文
        text = re.sub(r"\n*<!--\s*原书第.*?页\s*-->\n*", "\n\n", ocr_raw, flags=re.S)
        total_chars = len(text)
        if total_chars < 50:
            print(f"[跳过] MinerU 后仍提取不到内容（{total_chars} 字）。")
            return
    else:
        print(
            f"[跳过] {src.name} 不是 PDF。\n"
            "       只支持 PDF（全走 MinerU 云端识别，公式转 LaTeX）\n"
            "       或 00-MinerU解析全文.md 重切分。"
        )
        return

    # 切分方式：auto 一律优先按章节标题拆分（识别不到再退回按标题/字数）
    mode = args.split_mode
    if mode == "auto":
        mode = "chapter"

    chunks_meta = []
    chunk_no = 0
    units = None
    if mode == "chapter":
        generic = build_chapter_plan(text, getattr(args, "opener_pattern", ""))
        plan_info = generic
        how = "通用标题识别"
        end_pat = (getattr(args, "chapter_end_pattern", "") or "auto").strip()
        title_pat = getattr(args, "chapter_title_pattern", "")
        start_pat = getattr(args, "chapter_start_pattern", "")
        explicit = end_pat not in ("", "auto", "off", "none", "no")
        if end_pat.lower() in ("off", "none", "no"):
            end_pat = ""
        if end_pat == "auto":
            hint = f"{args.book_name} {src.stem} {src.parent.name}"
            for kw, ep, tp in END_ANCHOR_PRESETS:
                if kw.lower() in hint.lower():
                    end_pat, title_pat = ep, (title_pat or tp)
                    print(
                        f"[章界识别] 命中预设《{kw}》：按每章收尾小节定位章界"
                        f"（锚点正则：{ep}）"
                    )
                    break
            else:
                end_pat = ""
        cand = None
        if end_pat:
            cand = build_chapter_plan_by_end_anchor(text, end_pat, title_pat, start_pat)
        elif args.chapter_end_pattern:
            # auto 但没命中预设：从正文里自己挖「每章固定小节」
            cand = discover_chapter_plan(text)
        if cand and cand.get("bounds"):
            n_cand, n_cur = len(cand["bounds"]), len(plan_info["bounds"]) if plan_info else 0
            # 只有通用识别明显没切好（<4 章，或章数不到对方一半多一点）才改写，
            # 避免拿一个更细的重复小节把正常的章表拆碎
            better = n_cand > n_cur and (
                explicit or n_cur < 4 or n_cand >= n_cur * 2.2
            )
            if better:
                plan_info, how = cand, "按每章收尾小节定位"
                if not explicit:
                    print(f"[章界识别] 收尾小节定位 {n_cand} 章 > 通用识别 {n_cur} 章，用前者")
            else:
                print(
                    f"[章界识别] 收尾小节定位到 {n_cand} 章，不如通用识别（{n_cur} 章），"
                    "保留通用结果"
                )
        plan = plan_info["bounds"] if plan_info else None
        if plan:
            print(
                f"[标题识别] {how}：找到 {len(plan)} 个章节，按章节切分（一章一个文件）"
            )
            if plan_info.get("missing"):
                print(
                    "[提示] 以下章节未在正文定位到："
                    + "、".join(str(n) for n in plan_info["missing"])
                    + "（置信度低，可考虑校准）"
                )
            back_matter = plan_info.get("back_matter")
            units = []
            for i, (num, title, pos) in enumerate(plan):
                end = (
                    plan[i + 1][2]
                    if i + 1 < len(plan)
                    else (back_matter[0] if back_matter else len(text))
                )
                body = _strip_leading_heading(text[pos:end], title)
                units.append((num, title, body, pos))
            if back_matter:
                bm_title = back_matter[1]
                units.append((None, bm_title, text[back_matter[0] :], back_matter[0]))
                print(f"[提示] 检测到书后部分（{bm_title}），已保留为最后一个分块")
            front_matter = plan_info.get("front_matter")
            if front_matter:
                units.insert(0, (None, front_matter[1], text[: front_matter[0]], 0))
                print(f"[提示] 正文前的内容单独存为一个分块（{front_matter[1]}）")
        else:
            print("[提示] 未能从目录/页眉识别章节，退回按字数拆分。")
    if units is None:
        print(
            "[提示] 未能识别章节：为避免错误切分导致公式损坏，"
            "全书保存为一个文件，可后续用 AI 校准章节锚点后重切。"
        )
        units = [(None, "全书（未按章拆分，需校准）", text, 0)]

    for idx, (num, title, body, _pos) in enumerate(units, start=1):
        # 一章一个文件，章节内部不再切块（避免截断公式）
        chunk_no += 1
        piece = body
        preview = re.sub(r"\s+", " ", obsidian_img_links(piece))[:60]
        fname = f"章节{chunk_no:03d}-{safe_name(title)}.md"
        fpath = book_dir / fname
        if num:
            head = f"# 第 {num} 章 {title}"
        else:
            head = f"# {title}"
        fm_lines = [
            "---\n",
            "type: book-chunk\n",
            f"book_id: {book_id}\n",
            f"book: {book_name}\n",
            f"source_hash: {short_hash}\n",
            f"chapter: {idx}\n",
        ]
        if num:
            fm_lines.append(f"chapter_no: {num}\n")
        fm_lines += [
            "part: 1\n",
            f"chars: {len(piece)}\n",
            f"source: {src.name}\n",
            "---\n\n",
        ]
        content = "".join(fm_lines) + f"{head}\n\n" + f"{piece}\n"
        content = obsidian_img_links(content)
        atomic_write(fpath, content)
        chunks_meta.append((chunk_no, fname, title, len(piece), preview, idx))

    # 旧的、本次未生成的分块文件移入库外备份（防残留旧碎片）
    new_names = {m[1] for m in chunks_meta}
    stale = [p for p in book_dir.glob("章节*.md") if p.name not in new_names]
    if stale:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_root = book_backup_root(book_dir)
        dest = backup_root / stamp / "old-chunks"
        dest.mkdir(parents=True, exist_ok=True)
        for p in stale:
            shutil.move(str(p), dest / p.name)
        prune_backups(backup_root)
        print(f"[整理] 旧分块 {len(stale)} 个已备份到 {dest}")

    engine_note = {
        "text": "文字层直接提取",
        "mineru": "MinerU 云端解析（公式转 LaTeX）",
        "resplit": "从已有解析全文按标题重新切分",
    }.get(engine, engine)

    atomic_write(
        book_dir / "00-教材信息.md",
        "---\n"
        "type: book-info\n"
        f"book_id: {book_id}\n"
        f"book: {book_name}\n"
        f"source_hash: {source_hash}\n"
        f"engine: {engine}\n"
        "---\n\n"
        f"# 📕 {book_name}\n\n"
        f"- 来源文件：`{src}`\n"
        f"- 格式：{src.suffix.upper().lstrip('.')}\n"
        f"- 识别引擎：{engine_note}\n"
        f"- 总字符数：{total_chars:,}\n"
        f"- 识别章节数：{len(units)}\n"
        f"- 分块数：{chunk_no}\n"
        f"- 生成日期：{date.today().isoformat()}\n\n"
        "> 先打开 [[01-全书大纲]] 看全书骨架，再在 Claudian 里用\n"
        "> 「/新主题-拆解与计划」制定学习计划；每学完一章在纲目中勾选。\n",
    )

    if ocr_raw and engine == "mineru":
        atomic_write(
            book_dir / "00-MinerU解析全文.md",
            "---\n"
            "type: ocr-fulltext\n"
            f"book_id: {book_id}\n"
            f"source_hash: {short_hash}\n"
            f"engine: {engine}\n"
            "---\n\n"
            f"# 🔍 {book_name} 解析全文\n\n"
            f"> 由 MinerU 云端解析生成（扫描版 OCR + 公式转 LaTeX），"
            f"共 {total_chars:,} 字\n\n"
            f"{obsidian_img_links(ocr_raw)}\n",
        )
    # 全书目录大纲（章节清单 + 进度勾选）
    chapter_files = {}
    for _no, fname, _title, _clen, _preview, _ci in chunks_meta:
        chapter_files.setdefault(_ci, []).append(fname)
    outline = make_outline(
        book_id,
        short_hash,
        book_name,
        units,
        chapter_files,
        text,
        mode,
        src.name,
    )
    atomic_write(book_dir / "01-全书大纲.md", outline)

    toc_lines = [
        "---\n",
        "type: book-toc\n",
        f"book_id: {book_id}\n",
        f"source_hash: {short_hash}\n",
        "---\n\n",
        f"# 📑 {src.stem} 分块目录\n\n",
        "> 🗺️ 全书大纲：[[01-全书大纲]]\n\n",
        "| 块号 | 文件 | 章节 | 字数 | 内容预览 |\n",
        "| --- | --- | --- | ---: | --- |\n",
    ]
    for no, fname, title, clen, preview, _ci in chunks_meta:
        title_cell = title.replace("|", "\\|")[:20] or "—"
        preview_cell = preview.replace("|", "\\|")
        toc_lines.append(
            f"| {no} | [[{fname}]] | {title_cell} | {clen} | {preview_cell} |\n"
        )
    atomic_write(book_dir / "00-目录.md", "".join(toc_lines))

    print(f"完成：{len(units)} 个章节/小节，{chunk_no} 个分块 → {book_dir}")
    print("已生成：01-全书大纲.md（章节大纲 + 进度勾选）")
    if source_hash:
        print(f"book_id: {book_id} | source_hash: {short_hash}…（重复拆分会原地更新并备份旧文件）")


def main():
    parser = argparse.ArgumentParser(description="把厚教材拆成 AI 友好的小分块")
    parser.add_argument("input", help="教材文件或包含教材的文件夹")
    parser.add_argument("--out", default="04-教材分块", help="输出文件夹（默认 04-教材分块）")
    parser.add_argument(
        "--max-chars", type=int, default=0, help="已停用：一章一个文件，不再按字数切块"
    )
    parser.add_argument(
        "--overlap", type=int, default=0, help="已停用：一章一个文件，不再按字数切块"
    )
    parser.add_argument(
        "--ocr",
        choices=["mineru"],
        default="mineru",
        help="扫描版 PDF 用 MinerU 云端解析（公式转 LaTeX，免费 1000 页/天；本仓库唯一 OCR 路径）",
    )
    parser.add_argument(
        "--mineru-token",
        default="",
        help="MinerU Token（也可用环境变量 MINERU_TOKEN 或 设置MinerU令牌.sh 保存）",
    )
    parser.add_argument(
        "--mineru-cli",
        default="",
        help="mineru-open-api 可执行文件路径（默认自动查找）",
    )
    parser.add_argument(
        "--mineru-chunk-pages",
        type=int,
        default=200,
        help="每份上传的最大页数（MinerU 单文件限制 600 页/200MB，默认 200）",
    )
    parser.add_argument(
        "--mineru-chunk-mb",
        type=int,
        default=25,
        help="每份上传的最大体积 MB（默认 25；上传超时就调小，0=不限体积）",
    )
    parser.add_argument(
        "--mineru-dpi",
        type=int,
        default=200,
        help="扫描页降采样到的 DPI（默认 200，不影响识别精度；0=不压缩直传原件）",
    )
    parser.add_argument(
        "--mineru-language",
        default="en",
        help="文档语言：英文书用 en，中文书用 ch（默认 en）",
    )
    parser.add_argument(
        "--mineru-model",
        default="vlm",
        help="MinerU 模型：vlm（推荐）/ pipeline（默认 vlm）",
    )
    parser.add_argument(
        "--mineru-dry-run",
        action="store_true",
        help="只打印分块计划，不上传、不消耗额度",
    )
    parser.add_argument(
        "--split-mode",
        choices=["auto", "chapter"],
        default="auto",
        help="切分方式：auto=自动优先按章节标题（推荐）；chapter=按章节标题。"
        "一章一个文件，章节内部不再切分",
    )
    parser.add_argument(
        "--book-name",
        default="",
        help="指定书名/文件夹名（重切分 .md 全文时用于生成文件夹名）",
    )
    parser.add_argument(
        "--opener-pattern",
        default="",
        help="章节标题缺失时的补充定位：填每章都出现的开场小节标题正则，"
        "如意大利语教材每课都有的 'Impariamo a parlare'（可选）",
    )
    parser.add_argument(
        "--chapter-end-pattern",
        default="auto",
        help="每章固定收尾小节的正则（章标题被 OCR 打掉时的可靠办法），"
        "如 '作业\\s*\\(Trabajos de casa'；下一章从该行之后的第一个章标题/# 标题开始。"
        "默认 auto：先按书名命中共预设，没命中就从正文自动挖掘每章固定小节；"
        "off = 关掉只用通用标题识别",
    )
    parser.add_argument(
        "--chapter-title-pattern",
        default="",
        help="与 --chapter-end-pattern 配合：章起点标题行的特征正则（优先于“窗口内第一个 # 标题”），"
        "如 '^(?:#{1,6}\\s*)?(?:[A-Za-z田\\s]{0,8})?\\b(?:UNIDAD|第[0-9一二三四五六七八九十]+课$|课文\\s*TEXTOS)'"
        "（--chapter-end-pattern auto 会自动填）",
    )
    parser.add_argument(
        "--chapter-start-pattern",
        default="",
        help="与 --chapter-end-pattern 配合：第一章起点的正则"
        "（默认找第一个 课文/TEXTOS 标题）",
    )
    parser.add_argument(
        "--no-keep-images",
        action="store_true",
        help="MinerU 模式不保留解析出的图片（默认保留到分块文件夹 images/）",
    )
    args = parser.parse_args()

    src = Path(args.input)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        files = sorted(p for p in src.rglob("*") if p.suffix.lower() in SUPPORTED)
    else:
        files = [src]

    if not files:
        print("没有找到 PDF 文件。")
        return

    for f in files:
        if f.exists():
            process_file(f, out_root, args.max_chars, args.overlap, args)
        else:
            print(f"[跳过] 文件不存在：{f}")

    print("\n全部完成！在 Obsidian 里打开 04-教材分块/<书名>/ 即可看到分块笔记。")


if __name__ == "__main__":
    try:
        main()
    except (MineruUploadTimeout, MineruAuthError, RuntimeError) as exc:
        print(f"\n[失败] {exc}")
        print(
            "\n常见原因与对策："
            "\n  - 上传超时：把每份调小重跑，如 --mineru-chunk-mb 10"
            "（上行慢就 5），或 --mineru-dpi 150；"
            "\n    也可直接 --mineru-dry-run 先看分块计划（不耗额度）。"
            "\n  - Token/额度：去 https://mineru.net/apiManage/token 重新复制，"
            "再运行 _工具/设置MinerU令牌.bat。"
            "\n  - 云端排队/网络抖动：稍后重跑同一条命令即可。"
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[中断] 已停止，未消耗额度的部分下次重跑即可。")
        sys.exit(130)
