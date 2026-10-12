#Requires -Version 5.1
<#
.SYNOPSIS
    AI 学习工作流 · 一键安装（Release 引导器入口）
.DESCRIPTION
    由 HelpToStudy-QuickInstall.bat 下载并解压 Release 压缩包后自动调用，
    也可在解压后的仓库目录中手动运行。依次完成：
      1. 检测/安装环境：Obsidian、Python、Node.js、Git for Windows、
         Claude Code、cc-switch（已装则跳过）
      2. 安装「AI 学习工作流」Obsidian 库（保留文件夹选择对话框）
      3. 装完自动用 Obsidian 打开库
.PARAMETER SkipEnv
    跳过环境检测/安装，直接安装库。
.PARAMETER SkipClaude
    透传给 environment.ps1：跳过 Claude Code 检测与安装。
.PARAMETER EnvUpdate
    透传给 environment.ps1：检测到旧版本时直接升级，不再询问。
.PARAMETER VaultPath
    透传给 install.ps1：库的安装位置
    （默认 %USERPROFILE%\ObsidianVaults\AI学习工作流）。
.PARAMETER NoDialog
    透传给 install.ps1：不弹出文件夹选择对话框。
.PARAMETER SkipPython
    透传给 install.ps1：跳过 Python 虚拟环境与拆书依赖安装。
.PARAMETER SkipMineru
    透传给 install.ps1：跳过 MinerU 云端 OCR 工具安装。
.PARAMETER Force
    透传给 install.ps1：目标目录已存在时不询问，直接继续。
.PARAMETER NoOpenObsidian
    安装完成后不自动打开 Obsidian。
.PARAMETER Part
    装哪一部分：all（默认，学习部分 + 日程安排层）/ learn（只有学习部分）/
    schedule（只有日程安排层，可补装进已有库）。透传给 install.ps1；
    三个 Release 引导器已经分别带好了这个参数。
.EXAMPLE
    .\QuickInstall.ps1
    .\QuickInstall.ps1 -VaultPath "D:\我的资料\AI学习工作流" -NoOpenObsidian
    .\QuickInstall.ps1 -SkipEnv -NoDialog
    .\QuickInstall.ps1 -Part schedule
#>
param(
    [switch]$SkipEnv,
    [switch]$SkipClaude,
    [switch]$EnvUpdate,
    [string]$VaultPath = "",
    [switch]$NoDialog,
    [switch]$SkipPython,
    [switch]$SkipMineru,
    [switch]$Force,
    [switch]$NoOpenObsidian,
    [ValidateSet("all", "learn", "schedule", "全部", "学习", "日程")]
    [string]$Part = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [完成] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [提示] $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   AI 学习工作流 · 一键安装（Release 版）" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
$PartLabel = @{
    "all"      = "学习部分 + 日程安排层（全量）"
    "learn"    = "只装学习部分（不含 05-日程安排）"
    "schedule" = "只装日程安排层（补装到已有库）"
    "全部"     = "学习部分 + 日程安排层（全量）"
    "学习"     = "只装学习部分（不含 05-日程安排）"
    "日程"     = "只装日程安排层（补装到已有库）"
}[$Part]
if (-not $PartLabel) { $PartLabel = $Part }
Write-Host "   本次安装: $PartLabel"

# ---------- 1. 环境检测/安装 ----------
if (-not $SkipEnv) {
    Write-Step "第 1 步（共 2 步）：检测/安装环境（Obsidian / Python / Node.js / Git / Claude Code / cc-switch）"
    $envArgs = @{}
    if ($SkipClaude) { $envArgs["SkipClaude"] = $true }
    if ($EnvUpdate)  { $envArgs["Update"] = $true }
    try {
        & (Join-Path $Root "environment.ps1") @envArgs
        Write-OK "环境检测/安装完成"
    } catch {
        throw "环境配置失败：$($_.Exception.Message)"
    }
} else {
    Write-Warn "已跳过环境检测/安装（-SkipEnv）。请确保 Obsidian 与 Python 3.10+ 已安装。"
}

# ---------- 2. 安装库 ----------
Write-Step "第 2 步（共 2 步）：安装「AI 学习工作流」Obsidian 库"
# 哈希表 splat 才能按参数名绑定（数组 splat 只按位置传参）
$installArgs = @{}
if (-not $NoOpenObsidian) { $installArgs["OpenObsidian"] = $true }
if ($VaultPath) { $installArgs["VaultPath"] = $VaultPath }
if ($NoDialog)   { $installArgs["NoDialog"] = $true }
if ($SkipPython) { $installArgs["SkipPython"] = $true }
if ($SkipMineru) { $installArgs["SkipMineru"] = $true }
if ($Force)      { $installArgs["Force"] = $true }
$installArgs["Part"] = $Part
try {
    & (Join-Path $Root "install.ps1") @installArgs
} catch {
    throw "库安装失败：$($_.Exception.Message)"
}
# install.ps1 用 exit 1 表示用户主动取消（如文件夹选择/覆盖确认选 N）。
# 注意：-SkipPython 时 robocopy 成功也会留下退出码 1，因此只在非 -SkipPython 下提示。
if ($LASTEXITCODE -eq 1 -and -not $SkipPython) {
    Write-Warn "安装脚本返回退出码 1：若您刚才取消了文件夹选择或覆盖确认，属正常现象；否则请核对上方信息。"
}

Write-Host ""
Write-Host "============== 全部完成 ==============" -ForegroundColor Green
Write-Host "  库内容: $PartLabel"
Write-Host "  1) Obsidian 已打开（或在开始菜单中打开）"
Write-Host "  2) 首次打开若提示「信任社区插件」，请选择信任"
if ($Part -notin @("schedule", "日程")) {
    Write-Host "  3) 右侧边栏打开 Claudian，在设置里选择后端（本机 Codex 或 Claude Code）"
    Write-Host "  4) 扫描版/数学书才需要：运行 _工具\设置MinerU令牌.bat 保存 Token"
    Write-Host "  5) 打开 00-使用指南\📖 使用说明.md 开始使用"
}
if ($Part -in @("all", "schedule", "全部", "日程")) {
    Write-Host "  · 日程安排层：先填 05-日程安排\00-配置\规划配置.json，再跑 05-日程安排\_脚本\自检.bat 体检"
    Write-Host "  · 日历双后端（ics / Google）配置见 05-日程安排\00-配置\多端同步.md"
}
Write-Host "======================================" -ForegroundColor Green
