@echo off
chcp 65001 >nul
setlocal
set "DIR=%~dp0"
set "VAULT=%DIR%..\.."
if exist "%VAULT%\_工具\.venv\Scripts\python.exe" (
    set "PY=%VAULT%\_工具\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

rem =============================================================
rem  日程同步 · 统一入口（两个地位同等的后端）
rem      ics   本机 .ics 文件（零云依赖，可被云盘 / 手机订阅）
rem      gcal  Google 专用日历（多端原生同步）
rem
rem  用法：
rem     同步日程.bat                 按 00-配置\规划配置.json 的「同步.后端」跑
rem     同步日程.bat --后端 ics        只出 .ics
rem     同步日程.bat --后端 gcal       只推 Google
rem     同步日程.bat --dry-run        只看不写、不联网
rem =============================================================
set "BACKENDS="
set "PASSTHRU="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--后端" (
    set "BACKENDS=%~2"
    shift
    shift
    goto parse
)
set "PASSTHRU=%PASSTHRU% %~1"
shift
goto parse
:parsed
if not defined BACKENDS (
    for /f "usebackq delims=" %%b in (`"%PY%" -c "import json,pathlib;print(','.join(json.loads(pathlib.Path(r'%VAULT%\05-日程安排\00-配置\规划配置.json').read_text(encoding='utf-8')).get('同步',{}).get('后端',[]) or ['ics','gcal']))"`) do set "BACKENDS=%%b"
)
if not defined BACKENDS set "BACKENDS=ics,gcal"
echo [backends] %BACKENDS%
set "FAILED="
for %%b in (%BACKENDS:,= %) do (
    if /i "%%b"=="ics" (
        echo.
        echo ============ 1/2 ics backend: write local .ics ============
        "%PY%" "%DIR%导出ics.py" %PASSTHRU%
        if errorlevel 1 set "FAILED=1"
    ) else if /i "%%b"=="gcal" (
        echo.
        echo ============ 2/2 gcal backend: push to Google Calendar ============
        call "%DIR%同步日历.bat" %PASSTHRU%
        if errorlevel 1 set "FAILED=1"
    ) else (
        echo [ERROR] unknown backend: %%b  (use ics / gcal)
        set "FAILED=1"
    )
)
echo.
if defined FAILED (
    echo [WARN] some backend failed - see messages above
    pause
    exit /b 1
)
echo [OK] all backends done.
pause
exit /b 0
