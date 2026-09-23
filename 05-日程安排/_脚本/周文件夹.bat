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

rem 建本周文件夹（06-日志\<周号>\）并预建 7 篇日记；已存在的不覆盖
"%PY%" "%DIR%周文件夹.py" %*
if errorlevel 1 goto fail
echo.
pause
exit /b 0
:fail
echo.
echo [FAILED] 周文件夹创建失败，把上面的报错发给 AI。
pause
exit /b 1
