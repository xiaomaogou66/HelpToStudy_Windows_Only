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

rem 生成假期学习块（法定节假日每天 4–6h）——把输出原样贴进周决策的「① 本周任务」
rem 用法：假期块.bat 2026-W40   ｜ 假期块.bat（本周）
"%PY%" "%DIR%假期块.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] 假期块生成失败，把上面的报错发给 AI。
pause
exit /b 1
