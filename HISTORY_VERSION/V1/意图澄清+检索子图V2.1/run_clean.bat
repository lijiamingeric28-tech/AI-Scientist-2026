@echo off
REM 清除Python缓存并启动应用

echo 正在清除Python缓存...

REM 删除 __pycache__ 目录
for /d /r %%i in (__pycache__) do (
    if exist "%%i" (
        echo 删除: %%i
        rd /s /q "%%i"
    )
)

REM 删除 .pyc 文件
del /s /q *.pyc 2>nul

echo 缓存清除完成！
echo.
echo 正在启动应用...
python app.py
