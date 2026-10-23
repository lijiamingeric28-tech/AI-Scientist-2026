"""AstroQuery AI 桌面版打包入口（PyInstaller）。

等价于 `python -m web.desktop`：uvicorn（线程）+ pywebview 内嵌窗口，
窗口关闭即退出服务、端口自动避让、WebView2 渲染。
"""
import sys
from web.desktop import run_embedded

if __name__ == "__main__":
    if "--check" in sys.argv:
        print("[AstroQueryAI] Check OK: executable and dependencies loaded successfully.", flush=True)
        sys.exit(0)
    run_embedded()
