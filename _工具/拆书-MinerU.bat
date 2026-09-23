@echo off
rem 兼容旧文档 / 旧快捷方式：本文件现在只是转接到 拆书.bat 的薄壳。
rem 真正做事的是 _工具\拆书.bat（MinerU 单流程）。
call "%~dp0拆书.bat" %*
exit /b %errorlevel%
