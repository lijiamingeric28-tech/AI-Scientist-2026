@echo off
chcp 65001 >nul
pushd "%~dp0..\..\frontend"
call npm run demo:tour -- --mode present %*
set "DEMO_EXIT=%ERRORLEVEL%"
popd
if not "%DEMO_EXIT%"=="0" pause
exit /b %DEMO_EXIT%
