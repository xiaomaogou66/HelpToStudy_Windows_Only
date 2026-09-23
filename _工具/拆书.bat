@echo off
chcp 65001 >nul
set "SPLIT_OUTPUT_ENCODING=utf-8"
title Textbook Splitter - MinerU (cloud OCR + chapter split)

rem ================================================================
rem  拆书（唯一入口）：PDF -> MinerU 云端 OCR（公式转 LaTeX）-> 按章拆分
rem    也可把已有的 00-MinerU解析全文.md 拖进来重切分（不消耗额度）
rem
rem  额外参数（可选，直接跟在文件路径后面）：
rem    --mineru-chunk-mb 8     上传分块上限（MB，0 = 不限）
rem    --mineru-dpi 150        扫描页降采样 DPI（0 = 不压缩直传）
rem    --chapter-end-pattern off      关掉“每章固定收尾小节”定位
rem  例：拆书.bat "D:\书\某教材.pdf" --mineru-chunk-mb 8
rem
rem  本地文字层提取（pdfplumber / Word / EPUB）已下线：全走 MinerU。
rem ================================================================

rem ==== 所有路径都相对本文件，库可整包移动/拷贝 ====
set "VAULT=%~dp0.."
set "SCRIPT=%~dp0split_textbook.py"
set "OUT=%VAULT%\04-教材分块"
set "TOKEN_FILE=%~dp0mineru_token.txt"
set "REQ=%~dp0requirements.txt"

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

if exist "%~dp0.venv\Scripts\mineru-open-api.exe" (
    set "MINERU_CLI=%~dp0.venv\Scripts\mineru-open-api.exe"
) else if exist "%USERPROFILE%\obsidian-vault-mcp\.venv\Scripts\mineru-open-api.exe" (
    set "MINERU_CLI=%USERPROFILE%\obsidian-vault-mcp\.venv\Scripts\mineru-open-api.exe"
) else (
    set "MINERU_CLI="
    for /f "delims=" %%i in ('where mineru-open-api 2^>nul') do if not defined MINERU_CLI set "MINERU_CLI=%%i"
)

set "AIWF_MINERU_TOKEN_FILE=%TOKEN_FILE%"
if defined MINERU_CLI set "AIWF_MINERU_CLI=%MINERU_CLI%"

echo ================================================
echo   Textbook Splitter - MinerU (only path)
echo   PDF                 -^> MinerU OCR + chapter split
echo   00-MinerU解析全文.md -^> re-split by chapter (no quota)
echo ================================================
echo.

set "FILE=%~1"
if defined FILE goto check_type

echo Drag the PDF (or 00-MinerU解析全文.md) into this window and press Enter:
set /p "FILE="
set "FILE=%FILE:"=%"

:check_type
if not defined FILE set "FILE="
if "%FILE%"=="" (
    echo.
    echo No file path given. Exiting.
    pause
    exit /b 1
)

rem ==== 额外参数透传（%2 起，最多到 %9）====
set "EXTRA="
if not "%~2"=="" set "EXTRA=%~2"
if not "%~3"=="" set "EXTRA=%EXTRA% %~3"
if not "%~4"=="" set "EXTRA=%EXTRA% %~4"
if not "%~5"=="" set "EXTRA=%EXTRA% %~5"
if not "%~6"=="" set "EXTRA=%EXTRA% %~6"
if not "%~7"=="" set "EXTRA=%EXTRA% %~7"
if not "%~8"=="" set "EXTRA=%EXTRA% %~8"
if not "%~9"=="" set "EXTRA=%EXTRA% %~9"

echo.
echo Selected: %FILE%
if defined EXTRA echo Extra args: %EXTRA%
echo.

set "EXT=%FILE:~-3%"
if /i "%EXT%"==".md" goto resplit
goto mineru

:mineru
set "TOKEN="
if exist "%TOKEN_FILE%" set /p TOKEN=<"%TOKEN_FILE%"
if not defined TOKEN set "TOKEN="
if "%TOKEN%"=="" (
    echo.
    echo MinerU Token not saved yet.
    echo Run 设置MinerU令牌.bat once, or paste your token here:
    set /p "TOKEN=Paste MinerU Token: "
)

if not defined MINERU_CLI (
    echo.
    echo [ERROR] mineru-open-api not found. Install it with:
    echo   "%~dp0.venv\Scripts\pip.exe" install mineru-open-api
    echo or run the installer again without skipping MinerU.
    pause
    exit /b 1
)

echo Output: %OUT%
echo Uploading to MinerU cloud and splitting by chapter. A 750-page book
echo takes about 20-40 minutes. Please wait...
echo.

if "%TOKEN%"=="" (
    "%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --ocr mineru --split-mode chapter %EXTRA%
) else (
    "%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --ocr mineru --split-mode chapter --mineru-token "%TOKEN%" %EXTRA%
)
goto done

:resplit
echo MinerU full text detected. Re-splitting by chapter (no MinerU quota used)...
echo.
"%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --split-mode chapter %EXTRA%
goto done

:done
if errorlevel 1 goto fail
echo.
echo [OK] Done! Files are in "%OUT%".
echo.
pause
exit /b 0

:fail
echo.
echo [FAILED] Please send the error messages above to the AI.
echo Common causes: unstable network, invalid or expired Token (run the /拆书
echo command in Claudian for a token age check), daily quota exceeded.
echo.
pause
exit /b 1
