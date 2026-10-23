@echo off
REM ── AstroQuery AI 桌面绿色包一键构建与发布 ──
REM 产物:
REM   1. 绿色解压目录: dist\AstroQueryAI\AstroQueryAI.exe
REM   2. 独立发布包: release\AstroQueryAI-win64.zip
cd /d "%~dp0.."

echo [1/2] 检查与安装必要打包依赖 ...
"D:\miniconda\envs\py3.10\python.exe" -m pip install pyinstaller -q

echo [2/2] 执行全自动构建与发布（前端编译 + PyInstaller + 资源校验 + Zip打包）...
"D:\miniconda\envs\py3.10\python.exe" packaging\build_release.py
if %errorlevel% neq 0 (
    echo [FAILED] 构建失败，见上方日志
    exit /b 1
)

echo BUILD AND PACKAGING OK!
