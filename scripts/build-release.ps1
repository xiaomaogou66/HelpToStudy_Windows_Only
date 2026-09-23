#Requires -Version 5.1
<#
.SYNOPSIS
    构建 HelpToStudy 一键安装 Release 资产
.DESCRIPTION
    生成三个文件（默认输出到当前目录）：
      HelpToStudy-Vault-<tag>.zip    库完整内容（UTF-8 安全的中文文件名）
      HelpToStudy-QuickInstall.bat   一键入口（内嵌版本号与直链下载 URL）
      release-notes.md               Release 说明（中文）
    供 GitHub Actions（.github/workflows/release.yml）与本地手动发布使用。
.PARAMETER Tag
    版本号，如 v1.0.0（默认取最近的 git tag）。
.PARAMETER Repo
    GitHub 仓库 owner/name，如 xiaomaogou66/HelpToStudy（默认从 origin 解析）。
.PARAMETER OutDir
    资产输出目录（默认当前目录）。
.EXAMPLE
    .\scripts\build-release.ps1 -Tag v1.0.0 -Repo xiaomaogou66/HelpToStudy -OutDir .\dist
#>
param(
    [string]$Tag = "",
    [string]$Repo = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# ---------- 解析版本号 ----------
if (-not $Tag) {
    $Tag = git -C $RepoRoot describe --tags --abbrev=0 2>$null
    if (-not $Tag) { throw "未指定 -Tag，且仓库里没有可用 tag。请先打 tag 或传 -Tag v1.0.0" }
}
if ($Tag -notmatch '^v[0-9A-Za-z._-]+$') { throw "-Tag 必须是安全的版本号（如 v1.0.0），当前值：$Tag" }

# ---------- 解析仓库 ----------
if (-not $Repo) {
    $url = git -C $RepoRoot config --get remote.origin.url 2>$null
    if ($url -and $url -match 'github\.com[:/]([^/]+/[^/]+?)(\.git)?$') {
        $Repo = $Matches[1]
    }
    if (-not $Repo) { throw "无法从 origin 解析仓库名，请传 -Repo owner/name" }
}

if (-not $OutDir) { $OutDir = Get-Location }
$OutDir = [System.IO.Path]::GetFullPath([string]$OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$ZipName = "HelpToStudy-Vault-$Tag.zip"
$BatName = "HelpToStudy-QuickInstall.bat"
$ZipPath = Join-Path $OutDir $ZipName
$BatPath = Join-Path $OutDir $BatName
$NotesPath = Join-Path $OutDir "release-notes.md"

# 临时构建目录：避免把产物打进压缩包
$buildDir = Join-Path ([System.IO.Path]::GetTempPath()) ("HelpToStudy-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
try {
    # ---------- 1. 库压缩包（.NET ZipFile，中文/emoji 文件名 UTF-8 安全） ----------
    Write-Host "打包库内容 -> $ZipPath" -ForegroundColor Cyan
    $stage = Join-Path $buildDir "stage"
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    # robocopy 退出码 0-7 均为成功（1 = 已复制文件）
    # 排除：版本库 / 虚拟环境 / 缓存 / 本地专属词表 / 构建产物
& robocopy $RepoRoot $stage /E /XD .git .venv __pycache__ dist /XF scrub-map.local.txt /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制仓库失败（robocopy 退出码 $LASTEXITCODE）" }
    $tmpZip = Join-Path $buildDir $ZipName
    try { Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop } catch { }
    try { Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop } catch { }
    # 手动写条目：统一正斜杠 + UTF-8 编码，避免 Windows 反斜杠/emoji 问题，
    # 保证任何系统的解压工具（含 macOS/Linux）都能正确还原中文与 emoji 文件名。
    $fs = $null
    $archive = $null
    try {
        $fs = [System.IO.File]::Open($tmpZip, [System.IO.FileMode]::Create)
        $archive = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
        Get-ChildItem -LiteralPath $stage -Recurse -Force -File | ForEach-Object {
                $relative = $_.FullName.Substring($stage.Length + 1)
                $entryName = $relative.Replace("\", "/")
                $entry = $archive.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
                $stream = $entry.Open()
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
                    $stream.Write($bytes, 0, $bytes.Length)
                } finally {
                    $stream.Dispose()
                }
            }
    } finally {
        if ($archive) { $archive.Dispose() }
        if ($fs) { $fs.Dispose() }
    }
    Copy-Item -LiteralPath $tmpZip -Destination $ZipPath -Force

    # ---------- 2. 一键引导器（纯 ASCII + CRLF，内嵌版本号与直链） ----------
    $downloadUrl = "https://github.com/$Repo/releases/download/$Tag/$ZipName"
    $batTemplate = @'
@echo off
setlocal
title AI Learning Workflow - One-Click Installer
set "TAG=__TAG__"
set "REPO=__REPO__"
set "ZIP=__ZIP__"
set "URL=__URL__"
set "WORK=%TEMP%\HelpToStudy-%TAG%"

echo ================================================
echo   AI Learning Workflow - One-Click Installer
echo   Version: %TAG%
echo   It will download the vault package, check the
echo   environment, install the vault and open Obsidian.
echo ================================================
echo.

rem Download the vault package (up to 3 retries).
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%" 2>nul

echo [1/3] Downloading vault package ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; $url='%URL%'; $out='%WORK%\%ZIP%'; for($i=1;$i -le 3;$i++){ try { Invoke-WebRequest -Uri $url -OutFile $out -TimeoutSec 900 -UseBasicParsing; break } catch { if($i -eq 3){ Write-Host ('[FAILED] Download error: '+$_.Exception.Message); exit 1 }; Write-Host ('[WARN] Download failed, retrying '+$i+'/3 ...'); Start-Sleep -Seconds 5 } }"
if errorlevel 1 goto :fail

echo [2/3] Extracting vault package ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%WORK%\%ZIP%' -DestinationPath '%WORK%\vault' -Force"
if errorlevel 1 goto :fail
if not exist "%WORK%\vault\QuickInstall.ps1" goto :fail

echo [3/3] Installing (environment + vault + open Obsidian) ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORK%\vault\QuickInstall.ps1" %*
if errorlevel 1 goto :fail

echo.
echo [DONE] Installation finished. Press any key to close.
pause
exit /b 0

:fail
echo.
echo [FAILED] Something went wrong. Please read the messages above
echo         and send them to the AI. Press any key to close.
pause
exit /b 1
'@
    $bat = $batTemplate.Replace("__TAG__", $Tag).Replace("__REPO__", $Repo).Replace("__ZIP__", $ZipName).Replace("__URL__", $downloadUrl)
    $bat = $bat -replace "`r?`n", "`r`n"
    [System.IO.File]::WriteAllText($BatPath, $bat, [System.Text.Encoding]::ASCII)
    Write-Host "生成一键入口 -> $BatPath" -ForegroundColor Cyan

    # ---------- 3. Release 说明（中文，UTF-8） ----------
    $notes = @"
# AI 学习工作流 · $Tag

一套把「厚教材 → 能真正学会」的固定流程封装成可一键复现的 Obsidian 库：
拆书 → 五级水平拆解 → 二八定律学习计划 → 十问测试 → 一页速查表。

## 一键安装（Windows 10 / 11，推荐）

1. 下载本页资产 **HelpToStudy-QuickInstall.bat**
2. 双击运行，它会自动完成：
   - 从 Release 下载库压缩包并解压
   - 检测/安装环境：Obsidian、Python、Node.js、Git for Windows、
     Claude Code、cc-switch（已装则跳过）
   - 安装「AI 学习工作流」Obsidian 库（可弹窗自选位置）
   - 装完自动打开 Obsidian
3. 首次打开 Obsidian 若提示「信任社区插件」，选信任
4. 右侧边栏打开 Claudian，选择后端（本机 Codex 或 Claude Code）即可使用

> 浏览器若提示「不常见下载」，点击保留/仍要运行即可。脚本未签名，内容全部开源，
> 可在此仓库直接审阅。

## 常用参数

在 cmd / PowerShell 中追加参数运行：

```
.\HelpToStudy-QuickInstall.bat -VaultPath "D:\我的资料\AI学习工作流"
.\HelpToStudy-QuickInstall.bat -SkipEnv
.\HelpToStudy-QuickInstall.bat -SkipMineru -NoOpenObsidian
```

| 参数 | 作用 |
| --- | --- |
| `-SkipEnv` | 跳过环境检测/安装，只装库 |
| `-SkipClaude` | 跳过 Claude Code 安装 |
| `-VaultPath "路径"` | 指定库安装位置 |
| `-NoDialog` | 不弹文件夹选择框，用默认位置 |
| `-SkipPython` | 跳过 Python 虚拟环境与拆书依赖 |
| `-SkipMineru` | 不装 MinerU 云端 OCR 工具 |
| `-NoOpenObsidian` | 装完不自动打开 Obsidian |
| `-Force` | 目标目录已存在时不询问，直接继续 |

## 手动安装（备用）

下载 **HelpToStudy-Vault-$Tag.zip**，解压后先双击「环境配置.bat」，
再双击「安装.bat」。

## 常见问题

- **离线 / 下载失败**：直接下载 ZIP 资产，解压后手动运行
  「环境配置.bat」→「安装.bat」。
- **升级旧库**：再次运行本引导器；目标目录已存在时会询问是否继续，
  个人笔记不受影响，只覆盖/补充工作流文件。
- **macOS / Linux**：当前一键安装面向 Windows；拆书脚本
  `split_textbook.py` 本身跨平台。
"@
    [System.IO.File]::WriteAllText($NotesPath, $notes, [System.Text.Encoding]::UTF8)
    Write-Host "生成发布说明 -> $NotesPath" -ForegroundColor Cyan

    Write-Host ""
    Write-Host "============== 构建完成 ==============" -ForegroundColor Green
    Write-Host "  ZIP : $ZipPath"
    Write-Host "  BAT : $BatPath"
    Write-Host "  说明: $NotesPath"
    Write-Host "======================================" -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
}
