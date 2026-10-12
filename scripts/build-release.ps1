#Requires -Version 5.1
<#
.SYNOPSIS
    构建 HelpToStudy 一键安装 Release 资产
.DESCRIPTION
    生成「三个包 + 三个一键入口 + 说明」：
      HelpToStudy-Vault-<tag>.zip            全量（学习部分 + 日程安排层）
      HelpToStudy-学习版-Vault-<tag>.zip      只有学习部分（不含 05-日程安排）
      HelpToStudy-日程版-Vault-<tag>.zip      只有日程安排层 + 安装器（可后装到已有库）
      HelpToStudy-QuickInstall.bat           全量一键入口（-Part all）
      HelpToStudy-学习版-QuickInstall.bat     学习版一键入口（-Part learn）
      HelpToStudy-日程版-QuickInstall.bat     日程版一键入口（-Part schedule）
      release-notes.md                       Release 说明（中文）
    三个包互相独立：学习版能单独装；日程版能随时补装进已有库（个人笔记一律不动）。
    供 GitHub Actions（.github/workflows/release.yml）与本地手动发布使用。
.PARAMETER Tag
    版本号，如 v1.0.0（默认取最近的 git tag）。
.PARAMETER Repo
    GitHub 仓库 owner/name（默认从 origin 解析）。
.PARAMETER OutDir
    资产输出目录（默认当前目录）。
.PARAMETER Flavor
    只出某一个包：all / learn / schedule（默认三个都出）。
.EXAMPLE
    .\scripts\build-release.ps1 -Tag v1.0.0 -Repo xiaomaogou66/HelpToStudy_Windows_Only -OutDir .\dist
.EXAMPLE
    .\scripts\build-release.ps1 -Tag v1.0.0 -Flavor learn
#>
param(
    [string]$Tag = "",
    [string]$Repo = "",
    [string]$OutDir = "",
    [ValidateSet("all", "learn", "schedule", "全部", "学习", "日程")]
    [string]$Flavor = ""
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

# ---------- 三个包的定义 ----------
# part: all / learn / schedule —— 与 install.ps1 -Part 一一对应
# 学习版 = 全量去掉日程安排层（第六层）与它的两个命令、两个 skill
# 日程版 = 只放日程安排层 + 安装器 + 它的两个命令、两个 skill（可后装）
# 注意：资产名一律用 ASCII —— `gh` 会把非 ASCII 文件名截掉，中文名会传成 `-xxx.bat`
$PackageTable = @(
    [pscustomobject]@{
        Part  = "all"
        Label = "全量"
        Zip   = "HelpToStudy-Vault-$Tag.zip"
        Bat   = "HelpToStudy-QuickInstall.bat"
        Title = "AI Learning Workflow - full package"
    },
    [pscustomobject]@{
        Part  = "learn"
        Label = "学习版"
        Zip   = "HelpToStudy-Learn-Vault-$Tag.zip"
        Bat   = "HelpToStudy-Learn-QuickInstall.bat"
        Title = "AI Learning Workflow - learn only"
    },
    [pscustomobject]@{
        Part  = "schedule"
        Label = "日程版"
        Zip   = "HelpToStudy-Schedule-Vault-$Tag.zip"
        Bat   = "HelpToStudy-Schedule-QuickInstall.bat"
        Title = "AI Learning Workflow - schedule layer only"
    }
)

# -Flavor 可只构建其中一份（本地调试用；CI 不传 = 三份全出）
$FlavorMap = @{ "全部" = "all"; "学习" = "learn"; "日程" = "schedule" }
if ($Flavor -and $FlavorMap.ContainsKey($Flavor)) { $Flavor = $FlavorMap[$Flavor] }
$Packages = if ($Flavor) { $PackageTable | Where-Object { $_.Part -eq $Flavor } } else { $PackageTable }
if (-not $Packages) { throw "未知的 -Flavor：$Flavor（只能传 all / learn / schedule）" }

$NotesPath = Join-Path $OutDir "release-notes.md"

# 临时构建目录：避免把产物打进压缩包
$buildDir = Join-Path ([System.IO.Path]::GetTempPath()) ("HelpToStudy-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# ---------- 工具函数（定义放最前，避免调用顺序问题） ----------
function New-Stage([string]$Name, [switch]$LearnOnly, [switch]$ScheduleOnly) {
    $dir = Join-Path $buildDir $Name
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    if ($ScheduleOnly) {
        # 日程版：只挑跟日程安排层有关的东西（可后装进已有库，个人笔记不动）
        foreach ($p in $schedulePicks) {
            $src = Join-Path $RepoRoot $p
            if (-not (Test-Path -LiteralPath $src)) { Write-Host "  [提示] 日程版跳过缺失项：$p" -ForegroundColor Yellow; continue }
            $dst = Join-Path $dir $p
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            if (Test-Path -LiteralPath $src -PathType Container) {
                & robocopy $src $dst /E /XD .venv __pycache__ /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
                if ($LASTEXITCODE -ge 8) { throw "复制 $p 失败（robocopy 退出码 $LASTEXITCODE）" }
            } else {
                Copy-Item -LiteralPath $src -Destination $dst -Force
            }
        }
        return $dir
    }
    # robocopy 退出码 0-7 均为成功（1 = 已复制文件）
    # 排除：版本库 / 虚拟环境 / 缓存 / 本地专属词表 / 构建产物
    $rcArgs = @($RepoRoot, $dir, "/E", "/XD", ".git", ".venv", "__pycache__", "dist",
                "/XF", "scrub-map.local.txt")
    if ($LearnOnly) {
        # 学习版：日程安排层整个不要，连带它的两个命令 / 两个 skill
        $rcArgs += @("/XD", "05-日程安排", "/XF", "周决策.md", "课表.md", "zhou-jue-ce.md", "ke-biao.md")
    }
    $rcArgs += @("/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1")
    & robocopy @rcArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制仓库失败（robocopy 退出码 $LASTEXITCODE）" }
    return $dir
}

function Write-Zip([string]$Stage, [string]$ZipPath) {
    # 手动写条目：统一正斜杠 + UTF-8 编码，避免 Windows 反斜杠/emoji 问题，
    # 保证任何系统的解压工具（含 macOS/Linux）都能正确还原中文与 emoji 文件名。
    $tmpZip = Join-Path $buildDir ([System.IO.Path]::GetFileName($ZipPath))
    $fs = $null
    $archive = $null
    try {
        $fs = [System.IO.File]::Open($tmpZip, [System.IO.FileMode]::Create)
        $archive = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
        Get-ChildItem -LiteralPath $Stage -Recurse -Force -File | ForEach-Object {
                $relative = $_.FullName.Substring($Stage.Length + 1)
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
}

# 日程版要带的东西：日程安排层 + 安装器 + 那两个命令 / skill
$schedulePicks = @(
    "05-日程安排",
    "install.ps1", "QuickInstall.ps1", "environment.ps1",
    "环境配置.bat", "安装.bat", "workflow.config.json", "requirements.txt", "README.md",
    ".claude\commands\周决策.md", ".claude\commands\课表.md",
    ".pi\skills\zhou-jue-ce.md", ".pi\skills\ke-biao.md"
)

# 一键入口模板（纯 ASCII + CRLF，内嵌版本号、直链与 -Part）
$batTemplate = @'
@echo off
setlocal
title __TITLE__
set "TAG=__TAG__"
set "REPO=__REPO__"
set "ZIP=__ZIP__"
set "URL=__URL__"
set "PART=__PART__"
set "WORK=%TEMP%\HelpToStudy-%TAG%-%PART%"

echo ================================================
echo   __TITLE__
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
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORK%\vault\QuickInstall.ps1" -Part %PART% %*
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

try {
    try { Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop } catch { }
    try { Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop } catch { }

    # ---------- 1. 库压缩包（全量 / 学习版 / 日程版） ----------
    foreach ($pkg in $Packages) {
        $zipPath = Join-Path $OutDir $pkg.Zip
        Write-Host "打包 $($pkg.Label) -> $zipPath" -ForegroundColor Cyan
        $stage = New-Stage -Name "stage-$($pkg.Part)" `
                           -LearnOnly:($pkg.Part -eq "learn") `
                           -ScheduleOnly:($pkg.Part -eq "schedule")
        Write-Zip -Stage $stage -ZipPath $zipPath
    }

    # ---------- 2. 一键引导器（一个包一个入口） ----------
    foreach ($pkg in $Packages) {
        $downloadUrl = "https://github.com/$Repo/releases/download/$Tag/$($pkg.Zip)"
        $bat = $batTemplate.Replace("__TITLE__", $pkg.Title)
        $bat = $bat.Replace("__TAG__", $Tag)
        $bat = $bat.Replace("__REPO__", $Repo)
        $bat = $bat.Replace("__ZIP__", $pkg.Zip)
        $bat = $bat.Replace("__URL__", $downloadUrl)
        $bat = $bat.Replace("__PART__", $pkg.Part)
        $bat = $bat -replace "`r?`n", "`r`n"
        $batPath = Join-Path $OutDir $pkg.Bat
        [System.IO.File]::WriteAllText($batPath, $bat, [System.Text.Encoding]::ASCII)
        Write-Host "生成一键入口 -> $batPath" -ForegroundColor Cyan
    }

    # ---------- 3. Release 说明（中文，UTF-8） ----------
    $notes = @"
# AI 学习工作流 · $Tag

一套把「厚教材 → 能真正学会」的固定流程封装成可一键复现的 Obsidian 库：
拆书 → 五级水平拆解 → 二八定律学习计划 → 十问测试 → 一页速查表。

本版本把**学习部分**和**日程安排部分**分成了各自独立的包，想要哪一部分就装哪一部分；
两者都装就是完整的一套（日程版随时可以补装到已有库里，个人笔记一律不动）。

## 三种装法（Windows 10 / 11）

| 我想要 | 下载这个 | 装出来是什么 |
| --- | --- | --- |
| **只学**（拆书 / 主题 / 学案 / 测试 / 速查表） | **HelpToStudy-Learn-QuickInstall.bat**（学习版） | 学习部分：``00``–``04``、拆书工具、学习类命令与 skills |
| **只排日程**（周决策 / 打卡 / 课表 / 日历双后端） | **HelpToStudy-Schedule-QuickInstall.bat**（日程版） | 第六层：``05-日程安排/`` ＋ ``/周决策`` ``/课表``；可装进已有库 |
| **两个都要**（推荐） | **HelpToStudy-QuickInstall.bat**（全量） | 上面两部分，一次装好 |

三个包互不影响、可以叠加：先装学习版，之后想加日程就再跑一次日程版引导器。

## 装的时候会发生什么

1. 从 Release 下载对应压缩包并解压到临时目录
2. 检测/安装环境：**Obsidian、Python、Node.js、Git for Windows、Claude Code、cc-switch**
   （已装的最新版直接跳过；缺失的自动安装，来源优先级 winget > 官方接口 > 内置清单）
3. 安装库（默认 ``%USERPROFILE%\ObsidianVaults\AI学习工作流``；会弹文件夹选择框，可自选位置）
4. 装完自动用 Obsidian 打开库

> 浏览器若提示「不常见下载」，点击保留/仍要运行即可。脚本未签名，内容全部开源，
> 可在此仓库直接审阅。

## 常用参数

在 cmd / PowerShell 中追加参数运行：

```
.\HelpToStudy-QuickInstall.bat -VaultPath "D:\我的资料\AI学习工作流"
.\HelpToStudy-QuickInstall.bat -SkipEnv
.\HelpToStudy-Learn-QuickInstall.bat -NoOpenObsidian
.\HelpToStudy-Schedule-QuickInstall.bat -VaultPath "D:\我的资料\AI学习工作流"
```

| 参数 | 作用 |
| --- | --- |
| ``-SkipEnv`` | 跳过环境检测/安装，只装库 |
| ``-SkipClaude`` | 跳过 Claude Code 安装 |
| ``-VaultPath "路径"`` | 指定库安装位置 |
| ``-NoDialog`` | 不弹文件夹选择框，用默认位置 |
| ``-SkipPython`` | 跳过 Python 虚拟环境与拆书依赖 |
| ``-SkipMineru`` | 不装 MinerU 云端 OCR 工具 |
| ``-NoOpenObsidian`` | 装完不自动打开 Obsidian |
| ``-Force`` | 目标目录已存在时不询问，直接继续 |
| ``-Part 学习`` / ``-Part 日程`` / ``-Part 全部`` | 手动指定装哪一部分（三个引导器分别默认给好了） |

## 手动安装（备用）

下载对应的 ZIP（``HelpToStudy-Vault-$Tag.zip`` 全量 / ``HelpToStudy-Learn-Vault-$Tag.zip`` 学习版 /
``HelpToStudy-Schedule-Vault-$Tag.zip`` 日程版），解压后先双击「环境配置.bat」，再双击「安装.bat」。

## 常见问题

- **离线 / 下载失败**：直接下载 ZIP 资产，解压后手动运行「环境配置.bat」→「安装.bat」。
- **升级旧库**：再次运行对应引导器；目标目录已存在时会询问是否继续，
  个人笔记不受影响，只覆盖/补充工作流文件。
- **先装学习版、后加日程**：跑一次日程版引导器，选同一个库目录即可；
  它只补第六层与 ``/周决策`` ``/课表``，不动学习内容。
- **macOS / Linux**：当前一键安装面向 Windows；拆书脚本
  ``split_textbook.py`` 本身跨平台。
"@
    [System.IO.File]::WriteAllText($NotesPath, $notes, [System.Text.Encoding]::UTF8)
    Write-Host "生成发布说明 -> $NotesPath" -ForegroundColor Cyan

    Write-Host ""
    Write-Host "============== 构建完成 ==============" -ForegroundColor Green
    foreach ($pkg in $Packages) {
        Write-Host "  ZIP : $(Join-Path $OutDir $pkg.Zip)"
        Write-Host "  BAT : $(Join-Path $OutDir $pkg.Bat)"
    }
    Write-Host "  说明: $NotesPath"
    Write-Host "======================================" -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
}
