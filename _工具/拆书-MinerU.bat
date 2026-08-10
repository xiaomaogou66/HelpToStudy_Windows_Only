@echo off
chcp 65001 >nul
set "SPLIT_OUTPUT_ENCODING=utf-8"
title Textbook Splitter - MinerU (Cloud OCR + Chapter Split)

rem ==== All paths below are relative to this file, so the vault can be
rem       moved, copied or used on another computer without re-installing ====
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

rem Pass paths to the Python script
set "AIWF_MINERU_TOKEN_FILE=%TOKEN_FILE%"
if defined MINERU_CLI set "AIWF_MINERU_CLI=%MINERU_CLI%"

echo ================================================
echo   Textbook Splitter - MinerU All-in-One
echo   PDF        -^> MinerU cloud OCR + chapter split (LaTeX formulas)
echo   00-MinerU解析全文.md -^> re-split by chapters (no quota used)
echo ================================================
echo.

set "FILE=%~1"
if defined FILE goto check_type

echo Please drag the PDF or 00-MinerU解析全文.md into this window, then press Enter:
set /p "FILE="
set "FILE=%FILE:"=%

:check_type
if not defined FILE set "FILE="
if "%FILE%"=="" (
    echo.
    echo No file path given. Exiting.
    pause
    exit /b 1
)

echo.
echo Selected: %FILE%
echo.

rem .md = MinerU full text -^> re-split by chapters directly (no quota)
set "EXT=%FILE:~-3%"
if /i "%EXT%"==".md" goto resplit

goto mineru

:mineru
set "TOKEN="
if exist "%TOKEN_FILE%" (
    set /p TOKEN=<"%TOKEN_FILE%"
)
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
    "%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --ocr mineru --split-mode chapter
) else (
    "%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --ocr mineru --split-mode chapter --mineru-token "%TOKEN%"
)
goto done

:resplit
echo MinerU full text detected. Re-splitting by chapter (no MinerU quota used)...
echo.
"%PY%" "%SCRIPT%" "%FILE%" --out "%OUT%" --split-mode chapter
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
echo Common causes: unstable network, invalid Token, daily quota exceeded.
echo.
pause
exit /b 1
