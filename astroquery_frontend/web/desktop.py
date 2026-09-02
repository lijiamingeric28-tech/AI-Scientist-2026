"""内置引擎桌面入口（2026-09-01）：uvicorn（线程） + pywebview 窗口加载 127.0.0.1:<port>

- 不再依赖外部浏览器：窗口走 Win11 自带 WebView2（Chromium 内核控件），无地址栏/标签
- 端口：ASTROQUERY_PORT 指定优先，否则从 8000 起自动找空闲端口（避免与已开服务撞）
- 生命周期：窗口关闭 → uvicorn 一并退出（不留残留进程）
- 运行：python -m web.desktop
- pywebview 采用惰性导入：浏览器模式（packaging/launcher.py 默认）与测试环境不依赖它
"""
from __future__ import annotations

import os
import socket
import threading
import time

HOST = "127.0.0.1"
WINDOW_SIZE = (1500, 940)
WINDOW_MIN = (1100, 700)


def _pick_port(start: int) -> int:
    """start 起找空闲端口（绑定探测，探测后立即释放，uvicorn 随后独占）"""
    for port in range(start, start + 11):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"{start}-{start + 10} 端口区间均被占用，请释放端口或设置 ASTROQUERY_PORT")


def _apply_window_icon(window, ico_path: str) -> None:
    """窗口标题栏/任务栏图标（WinForms 后端：window.native 是 System.Windows.Forms.Form，
    经 pythonnet 设 .Icon）。纯装饰——任何失败静默跳过，不阻塞窗口。
    2026-09-01: pywebview 无 create_window(icon=)，这是唯一入口。"""
    try:
        from System.Drawing import Icon as _WinIcon  # pythonnet
        window.native.Icon = _WinIcon(ico_path)
    except Exception:  # noqa: BLE001
        pass


def run_embedded(host: str = HOST, port: int | None = None) -> None:
    """核心启动：服务线程 + 桌面窗口（可在 launcher/PyInstaller 中复用）。
    port=None → ASTROQUERY_PORT → 自动找空闲。"""
    try:
        import webview  # 惰性：非桌面流程不依赖 pywebview
    except ImportError as _exc:  # noqa: BLE001
        raise SystemExit("pywebview 未安装：pip install pywebview（或重新安装项目依赖）") from _exc

    from .main import app as fastapi_app  # 复用现有装配（含 frontend/dist 静态挂载）

    if port is None:
        env_port = os.environ.get("ASTROQUERY_PORT", "")
        port = _pick_port(int(env_port)) if env_port.isdigit() else _pick_port(8000)

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        fastapi_app, host=host, port=port, log_level="warning",
    ))
    threading.Thread(target=server.run, daemon=True).start()

    # 服务就绪再挂窗口（快速失败给出明确错误，而非窗口白屏）
    deadline = time.time() + 15
    while time.time() < deadline and not server.started:
        time.sleep(0.2)
    if not server.started:
        raise SystemExit(f"服务启动失败（{host}:{port}），请检查后端日志")

    window = webview.create_window(
        "AstroQuery AI",
        url=f"http://{host}:{port}",
        width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN,
    )
    # 窗口图标：项目根 icon.ico（多尺寸，icon.svg 派生；loaded 后 native 窗体已就绪）
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _ico = os.path.join(root_dir, "icon.ico")
    if os.path.isfile(_ico):
        window.events.loaded += lambda: _apply_window_icon(window, _ico)
    # 窗口关闭 → 停服务（线程 is daemon，但显式置位避免 uvicorn 在关闭竞态中继续收请求）
    window.events.closed += lambda: setattr(server, "should_exit", True)
    webview.start()
    server.should_exit = True


def main() -> None:
    run_embedded()


if __name__ == "__main__":
    main()
