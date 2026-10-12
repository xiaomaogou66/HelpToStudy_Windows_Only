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

rem 刷新法定节假日表（00-配置\节假日.json），拉官方数据（跟国务院通知同步）
rem 用法：更新节假日.bat           今年 + 明年
rem       更新节假日.bat 2026 2027 指定年份
rem       更新节假日.bat --dry-run  只看不写
"%PY%" "%DIR%更新节假日.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] 节假日表刷新失败（多半是没联网，或那一年还没公布），把上面的报错发给 AI。
pause
exit /b 1
