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

rem 生成本周打卡页（重复运行只补缺失项，不清掉已勾的）
"%PY%" "%DIR%打卡.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] 打卡页生成失败，把上面的报错发给 AI。
pause
exit /b 1
