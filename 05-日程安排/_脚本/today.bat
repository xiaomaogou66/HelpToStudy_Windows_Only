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

rem 今天看什么：周表 + 连续打卡 + 里程碑倒计时
rem   直接双击 = 看今天；today.bat done = 打卡；today.bat 周三 = 看某天
"%PY%" "%DIR%today.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] today 运行失败，把上面的报错发给 AI。
pause
exit /b 1
