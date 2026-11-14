@echo off
chcp 65001 >nul
call "%~dp0开始演示.cmd" %*
exit /b %ERRORLEVEL%
