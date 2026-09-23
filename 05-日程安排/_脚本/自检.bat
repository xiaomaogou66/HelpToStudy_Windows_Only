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

rem 日程安排层自检（不联网、不改数据；加 --联网 才查 Google 凭据）
"%PY%" "%DIR%自检.py" %*
echo.
pause
exit /b 0
