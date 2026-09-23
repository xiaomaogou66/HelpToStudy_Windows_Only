#Requires -Version 5.1
<#
.SYNOPSIS
    AI 学习工作流 · 一键安装脚本
.DESCRIPTION
    在一台新电脑上复现「AI 学习工作流」Obsidian 库：
      0. 交互模式下会先弹出「选择文件夹」对话框，由你决定库的安装位置
         （取消则询问是否用默认位置；-NoDialog 可跳过对话框）
      1. 在目标位置创建完整的库目录结构
      2. 复制模板、提示词、Claude 斜杠命令、Obsidian 配置与插件
      3. 创建 Python 虚拟环境并安装拆书依赖（含可选 MinerU 云端 OCR）
      4. 生成带本机路径的拆书启动器（_工具/*.bat）
      5. 可选：安装完成后直接用 Obsidian 打开该库
    用法（在仓库根目录的 PowerShell 中执行）：
      .\install.ps1
      .\install.ps1 -VaultPath "D:\我的资料\AI学习工作流" -OpenObsidian
      .\install.ps1 -SkipPython -SkipMineru
.PARAMETER VaultPath
    库的安装位置（默认 %USERPROFILE%\ObsidianVaults\AI学习工作流）
.PARAMETER PythonPath
    指定 python.exe 路径（默认自动查找）
.PARAMETER SkipPython
    跳过 Python 虚拟环境与依赖安装
.PARAMETER SkipMineru
    跳过 MinerU 云端 OCR 命令行工具安装
.PARAMETER SkipPlugins
    跳过 Obsidian 插件复制
.PARAMETER OpenObsidian
    安装完成后用 Obsidian 打开该库
.PARAMETER NoDialog
    不弹出文件夹选择对话框（直接使用默认位置；适合脚本化/无人值守安装）
.PARAMETER Force
    目标目录已存在时不再询问，直接继续
.EXAMPLE
    .\install.ps1 -OpenObsidian
.EXAMPLE
    .\install.ps1 -NoDialog -SkipPython
#>
param(
    [string]$VaultPath = "",
    [string]$PythonPath = "",
    [switch]$SkipPython,
    [switch]$SkipMineru,
    [switch]$SkipPlugins,
    [switch]$OpenObsidian,
    [switch]$NoDialog,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ---------- 工具函数 ----------
function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [完成] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [提示] $msg" -ForegroundColor Yellow }

function Invoke-PipWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$PipExe,
        [Parameter(Mandatory = $true)][string[]]$PipArgs,
        [Parameter(Mandatory = $true)][string]$Label
    )
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & $PipExe @PipArgs
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -lt 3) {
            Write-Warn "$Label 第 $attempt 次尝试失败，5 秒后自动重试（网络波动常见，最多重试 3 次）"
            Start-Sleep -Seconds 5
        }
    }
    throw "$Label 安装失败，请检查网络后重新运行 install.ps1"
}

# ---------- 读取配置 ----------
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VaultName = "AI学习工作流"
$cfg = @{}
$cfgPath = Join-Path $RepoRoot "workflow.config.json"
if (Test-Path -LiteralPath $cfgPath) {
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-OK "已读取配置文件 workflow.config.json"
    } catch {
        Write-Warn "配置文件解析失败，改用命令行参数与默认值"
    }
}
if (-not $VaultPath -and $cfg.vaultPath) { $VaultPath = [string]$cfg.vaultPath }
if (-not $PythonPath -and $cfg.pythonPath) { $PythonPath = [string]$cfg.pythonPath }
if (-not $SkipMineru -and $cfg.installMineru -eq $false) { $SkipMineru = $true }

$defaultVaultPath = Join-Path $env:USERPROFILE "ObsidianVaults\$VaultName"
if (-not $VaultPath) {
    $VaultPath = $defaultVaultPath
    # 方案 B：交互模式下弹出「选择文件夹」对话框，让用户自选库的位置。
    # 所选文件夹将直接作为库目录（与 -VaultPath 语义一致）。
    if (-not $NoDialog -and [Environment]::UserInteractive) {
        try {
            Add-Type -AssemblyName System.Windows.Forms | Out-Null
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = "请选择「AI 学习工作流」库的安装位置：" +
                "所选文件夹将直接作为库目录（默认：$defaultVaultPath）"
            $dialog.SelectedPath = Split-Path -Parent $defaultVaultPath
            $dialog.ShowNewFolderButton = $true
            if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) {
                $VaultPath = $dialog.SelectedPath
                Write-OK "已选择安装位置：$VaultPath"
            } else {
                $ans = Read-Host "未选择位置。使用默认位置 $defaultVaultPath ？(Y/N)"
                if ($ans -notmatch "^[yY]") { Write-Host "已取消安装"; exit 1 }
            }
            $dialog.Dispose()
        } catch {
            Write-Warn "无法弹出文件夹选择对话框，将使用默认位置：$defaultVaultPath"
            $VaultPath = $defaultVaultPath
        }
    }
}
$VaultPath = [System.IO.Path]::GetFullPath($VaultPath)

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   AI 学习工作流 · 一键安装" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   安装位置: $VaultPath"

# 已存在处理
if (Test-Path -LiteralPath $VaultPath) {
    $existing = (Get-ChildItem -LiteralPath $VaultPath -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($existing -gt 0 -and -not $Force) {
        Write-Warn "目标目录已存在且非空：$VaultPath"
        $ans = Read-Host "继续会覆盖其中的模板/命令/工具文件（个人笔记不受影响）。输入 y 继续"
        if ($ans -notmatch "^[yY]") { Write-Host "已取消安装"; exit 1 }
    }
    if ($existing -gt 0) { Write-Warn "目标目录已存在：保留现有个人笔记，覆盖/补充工作流文件" }
}

# ---------- 1. 创建目录 ----------
Write-Step "第 1 步：创建库目录结构"
$dirs = @(
    "00-使用指南", "01-提示词库", "02-模板", "03-学习主题", "04-教材分块",
    "_工具", "copilot\copilot-custom-prompts", "images",
    "05-日程安排\00-配置", "05-日程安排\_脚本", "05-日程安排\06-日志",
    "05-日程安排\_资源\日历", "05-日程安排\_归档", ".pi\skills"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $VaultPath $d) | Out-Null
}
Write-OK "目录结构已就绪"

# ---------- 2. 复制内容 ----------
Write-Step "第 2 步：复制模板 / 提示词 / 命令 / 配置"
$copyDirs = @("00-使用指南", "01-提示词库", "02-模板", "05-日程安排", ".claude", ".pi", "copilot", ".obsidian")
foreach ($d in $copyDirs) {
    $src = Join-Path $RepoRoot $d
    if (-not (Test-Path -LiteralPath $src)) { continue }
    if ($d -eq ".obsidian" -and $SkipPlugins) {
        robocopy $src (Join-Path $VaultPath $d) /E /XD plugins /XF data.json workspace.json /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null
    } else {
        robocopy $src (Join-Path $VaultPath $d) /E /XF data.json workspace.json /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null
    }
    if ($LASTEXITCODE -ge 8) { throw "复制 $d 失败（错误码 $LASTEXITCODE）" }
}
Copy-Item -LiteralPath (Join-Path $RepoRoot "03-学习主题\📌 从这里开始.md") -Destination (Join-Path $VaultPath "03-学习主题\") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "04-教材分块\📖 教材分块说明.md") -Destination (Join-Path $VaultPath "04-教材分块\") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "AGENTS.md") -Destination $VaultPath -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "CLAUDE.md") -Destination $VaultPath -Force
# _工具 整目录复制：拆书脚本 + 相对路径启动器 + requirements.txt（排除虚拟环境与缓存）
robocopy (Join-Path $RepoRoot "_工具") (Join-Path $VaultPath "_工具") /E /XD .venv __pycache__ /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 _工具 失败（错误码 $LASTEXITCODE）" }
# 日程安排层：任何密钥 / 令牌类文件都不带入目标库
@("calender-*.json", "service-account*.json", "token.json", "credentials.json") | ForEach-Object {
    Get-ChildItem -Path (Join-Path $VaultPath "05-日程安排\_脚本") -Filter $_ -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
Get-ChildItem -Path (Join-Path $VaultPath "05-日程安排") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 课表：没有真课表就先放一份示例，跑 自检 / 打卡 不会空转
$courseIcs = Join-Path $VaultPath "05-日程安排\_资源\日历\课表-当前.ics"
if (-not (Test-Path -LiteralPath $courseIcs)) {
    $sample = Join-Path $RepoRoot "05-日程安排\_资源\日历\课表示例.ics"
    if (Test-Path -LiteralPath $sample) { Copy-Item -LiteralPath $sample -Destination $courseIcs -Force }
}
Write-OK "内容复制完成"

# ---------- 3. Python 环境 ----------
$venvPy = Join-Path $VaultPath "_工具\.venv\Scripts\python.exe"
$py = ""
if (-not $SkipPython) {
    Write-Step "第 3 步：创建 Python 虚拟环境并安装拆书依赖"
    $py = $PythonPath
    if (-not $py) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if (-not $cmd) { $cmd = Get-Command py -ErrorAction SilentlyContinue }
        if ($cmd) { $py = $cmd.Source }
    }
    if (-not $py) {
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
            "$env:ProgramFiles\Python313\python.exe",
            "$env:ProgramFiles\Python312\python.exe",
            "$env:ProgramFiles\Python311\python.exe"
        )
        $py = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $py) {
        throw "未找到 Python。请先安装 Python 3.10+（https://www.python.org/downloads/），或用 -PythonPath 参数指定 python.exe"
    }
    Write-Host "  使用 Python: $py"
    if (-not (Test-Path -LiteralPath $venvPy)) {
        & $py -m venv (Join-Path $VaultPath "_工具\.venv")
        if ($LASTEXITCODE -ne 0) { throw "创建 Python 虚拟环境失败" }
    }
    Invoke-PipWithRetry -PipExe $venvPy -PipArgs @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", (Join-Path $RepoRoot "requirements.txt")) -Label "拆书依赖"
    Write-OK "拆书依赖已安装（pypdf；本地文字层提取已下线，拆书全走 MinerU）"

    if (-not $SkipMineru) {
        try {
            Invoke-PipWithRetry -PipExe $venvPy -PipArgs @("-m", "pip", "install", "--disable-pip-version-check", "-q", "mineru-open-api") -Label "MinerU 工具"
            Write-OK "MinerU 云端 OCR 工具已安装"
        } catch {
            Write-Warn "MinerU 工具安装失败，可稍后手动执行：_工具\.venv\Scripts\pip.exe install mineru-open-api"
        }
    }

    # 日程安排层依赖（Google 日历后端 + Windows 时区库）；装不上也不影响 ics 后端
    $schedReq = Join-Path $RepoRoot "05-日程安排\_脚本\requirements.txt"
    if (Test-Path -LiteralPath $schedReq) {
        try {
            Invoke-PipWithRetry -PipExe $venvPy -PipArgs @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", $schedReq) -Label "日程同步依赖"
            Write-OK "日程同步依赖已安装（google-api-python-client / google-auth-oauthlib / PySocks / tzdata）"
        } catch {
            Write-Warn "日程同步依赖没装上：Google 后端暂不可用，ics 后端不受影响。"
            Write-Warn "稍后可手动执行：_工具\.venv\Scripts\pip.exe install -r 05-日程安排\_脚本\requirements.txt"
        }
    }
} else {
    Write-Warn "已跳过 Python 环境安装（-SkipPython）"
}

# ---------- 4. 收尾 ----------
Write-Step "第 4 步：收尾"
Write-Host ""
Write-Host "============== 安装完成 ==============" -ForegroundColor Green
Write-Host "  库位置: $VaultPath"
Write-Host ""
Write-Host "  接下来："
Write-Host "  1) 用 Obsidian 打开该文件夹（作为库）"
Write-Host "  2) 首次打开若提示「信任社区插件」，请选择信任"
Write-Host "  3) 右侧边栏打开 Claudian，在设置里选择后端（本机 Codex 或 Claude Code）"
Write-Host "  4) 扫描版/数学书才需要：运行 _工具\设置MinerU令牌.bat 保存 Token"
Write-Host "  5) （可选）自检一遍：05-日程安排\_脚本\自检.bat"
Write-Host "  6) 打开 00-使用指南\📖 使用说明.md 开始使用"
Write-Host "======================================" -ForegroundColor Green

if ($OpenObsidian) {
    $obsidianUri = "obsidian://open?path=" + [uri]::EscapeDataString($VaultPath)
    Start-Process $obsidianUri
    Write-OK "已尝试用 Obsidian 打开该库"
}
