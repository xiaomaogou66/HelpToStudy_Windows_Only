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
rem  gcal 后端：把周决策任务 + 课表推到 Google 专用日历
rem  用法：同步日历.bat [--dry-run] [--check] [--list-calendars]
rem
rem  代理（只有这一个脚本走代理，不动系统代理）：
rem     默认走本机 127.0.0.1:7897（Clash / mihomo 常用口）
rem     换端口：  set SYNC_PROXY=http://127.0.0.1:7890 && 同步日历.bat
rem     临时直连：set SYNC_PROXY=none && 同步日历.bat
rem =============================================================
set "PROXY=%SYNC_PROXY%"
if not defined PROXY set "PROXY=http://127.0.0.1:7897"
if /i "%PROXY%"=="none" (
    set "HTTP_PROXY="
    set "HTTPS_PROXY="
    echo [proxy] direct connection (SYNC_PROXY=none)
) else (
    set "HTTP_PROXY=%PROXY%"
    set "HTTPS_PROXY=%PROXY%"
    echo [proxy] %PROXY%
)
"%PY%" -c "import googleapiclient, google_auth_oauthlib" 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Missing dependencies. Install them with:
    echo   "%PY%" -m pip install -r "%DIR%requirements.txt"
    echo or run the installer again.
    pause
    exit /b 1
)
"%PY%" "%DIR%sync_gcal.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] 同步失败，把上面的报错发给 AI（或看 _脚本\README-首次配置.md）。
pause
exit /b 1
