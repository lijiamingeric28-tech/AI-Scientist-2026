"""AstroQuery 绿色免安装包入口（PyInstaller onedir 主程序）

职责：
1. 解析包根（exe 所在目录）与数据目录（exe 旁 data/）
2. 设置 ASTROQUERY_DATA_DIR / ASTROQUERY_FRONTEND_DIR 环境变量
   （web/main.py 与 quality/subgraph2 均读这两个变量外置可写目录）
3. 启动 uvicorn 服务 + 自动打开浏览器
4. Ctrl+C / 窗口关闭时优雅退出
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("ASTROQUERY_PORT", "8000"))
STARTUP_DELAY = 3.0  # 等服务就绪再开浏览器


def _app_root() -> Path:
    """绿色包根：exe 所在目录（PyInstaller onedir 下 sys.executable 指向 exe）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 开发模式：项目根
    return Path(__file__).resolve().parent.parent


def _data_dir(root: Path) -> Path:
    """可写数据目录：包根旁 data/（开发模式为项目根 data/）"""
    return Path(os.environ.get("ASTROQUERY_DATA_DIR", str(root / "data")))


def main() -> None:
    root = _app_root()
    data = _data_dir(root)
    os.environ["ASTROQUERY_DATA_DIR"] = str(data)

    # 前端静态资源：spec 的 datas 打进 _internal/resources/frontend_dist
    # （PyInstaller onedir 的 datas 一律落在 _internal/）；开发模式直接指向 frontend/dist
    fe = root / "_internal" / "resources" / "frontend_dist"
    if not (fe / "index.html").exists():
        fe = root / "resources" / "frontend_dist"
    if not (fe / "index.html").exists():
        fe = root / "frontend" / "dist"
    os.environ["ASTROQUERY_FRONTEND_DIR"] = str(fe)

    data.mkdir(parents=True, exist_ok=True)
    (data / "output").mkdir(parents=True, exist_ok=True)
    (data / "web").mkdir(parents=True, exist_ok=True)
    (data / "papers").mkdir(parents=True, exist_ok=True)

    # 首次启动：.env 不存在则写模板（提示填写 API Key）
    env_path = data / ".env"
    if not env_path.exists():
        env_path.write_text(
            "# AstroQuery 配置（阿里云百炼 Qwen 必需）\n"
            "DASHSCOPE_API_KEY=\nDASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1\n"
            "ADS_API_TOKEN=\nUNPAYWALL_EMAIL=\n", encoding="utf-8")
    # 把 data/.env 注入进程环境（pydantic-settings 的 os.environ 优先级高于 env_file，
    # setdefault 保证外部已显式设置的变量优先）；打包后 config.py 的 env_file 指向
    # 只读 _internal，因此这里统一接管。
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    def _open_browser() -> None:
        time.sleep(STARTUP_DELAY)
        webbrowser.open(f"http://{HOST}:{PORT}")

    threading.Thread(target=_open_browser, daemon=True).start()

    # 显式 import app（而非字符串 "web.main:app"），PyInstaller 才能静态分析到 web.main
    from web.main import app as fastapi_app

    import uvicorn
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
