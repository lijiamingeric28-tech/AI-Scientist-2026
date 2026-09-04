@echo off
REM ── AstroQuery AI 桌面绿色包一键构建 ──
REM 产物: dist\AstroQueryAI\AstroQueryAI.exe（整个文件夹压缩即发布包）
REM 首次运行需在 exe 旁边放置 .env（API Key），格式见项目根 README/AstroQuery_AI/.env 模板
cd /d "%~dp0.."

echo [1/3] 安装 PyInstaller ...
"D:\miniconda\envs\py3.10\python.exe" -m pip install pyinstaller -q

echo [2/3] PyInstaller 构建（10-30 分钟，请耐心等待）...
"D:\miniconda\envs\py3.10\python.exe" -m PyInstaller --noconfirm --clean packaging\astroquery_ai.spec
if %errorlevel% neq 0 (
    echo [FAILED] 构建失败，见上方日志
    exit /b 1
)

echo [3/3] 完毕
echo BUILD OK: dist\AstroQueryAI\AstroQueryAI.exe
