"""内置引擎桌面入口（2026-09-01）：uvicorn（线程） + pywebview 窗口加载 127.0.0.1:<port>

- 不再依赖外部浏览器：窗口走 Win11 自带 WebView2（Chromium 内核控件），无地址栏/标签
- 端口：ASTROQUERY_PORT 指定优先，否则从 8000 起自动找空闲端口（避免与已开服务撞）
- 生命周期：窗口关闭 → uvicorn 一并退出（不留残留进程）
- 运行：python -m web.desktop
- pywebview 采用惰性导入：浏览器模式（直接用浏览器访问服务端口）与测试环境不依赖它
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


def _set_app_user_model_id() -> None:
    """任务栏图标根因（2026-09-02）：winforms 下 window.native.Icon 只影响标题栏，
    任务栏按钮在未绑定 AppUserModelID 时恒回落进程 exe 图标（python.exe）。
    SetCurrentProcessExplicitAppUserModelID 绑定后任务栏取窗口图标。"""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AstroQueryAI")
    except Exception:  # noqa: BLE001
        pass


def _apply_taskbar_icon(window, ico_path: str) -> None:
    """任务栏大图标（2026-09-02 fix L2）：webview.start(icon=) 只影响标题栏/小图标，
    Windows 任务栏按钮跟随 WM_SETICON(ICON_BIG)。loaded 回调内显式发送。
    前置 clr.AddReference 保证 System.Drawing 已加载（此前静默失败根因）。"""
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing import Icon as _WinIcon
        import ctypes
        import sys
        native = window.native
        print(f"[icon-debug] native={type(native).__name__}", flush=True)
        hwnd_attr = getattr(native, "Handle", None)
        print(f"[icon-debug] Handle attr={hwnd_attr}", flush=True)
        if hwnd_attr is None:
            return
        hwnd = int(hwnd_attr.ToInt64()) if hasattr(hwnd_attr, "ToInt64") else int(hwnd_attr)
        print(f"[icon-debug] hwnd={hwnd} isIcon={bool(ctypes.windll.user32.IsIconic(hwnd))}", flush=True)
        icon = _WinIcon(ico_path)
        hicon = int(icon.Handle.ToInt64()) if hasattr(icon.Handle, "ToInt64") else int(icon.Handle)
        print(f"[icon-debug] hicon={hicon}", flush=True)
        WM_SETICON = 0x0080
        ICON_BIG = 1
        ICON_SMALL = 0
        r1 = ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        r2 = ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
        print(f"[icon-debug] SendMessage big={r1} small={r2}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[icon-debug] FAIL: {type(e).__name__}: {e}", flush=True)


def run_embedded(host: str = HOST, port: int | None = None) -> None:
    """核心启动：服务线程 + 桌面窗口。
    port=None → ASTROQUERY_PORT → 自动找空闲。"""
    try:
        import webview  # 惰性：非桌面流程不依赖 pywebview
    except ImportError as _exc:  # noqa: BLE001
        raise SystemExit("pywebview 未安装：pip install pywebview（或重新安装项目依赖）") from _exc

    from .main import app as fastapi_app  # 复用现有装配（含 frontend/dist 静态挂载）

    # 任务栏图标绑定（须在窗口创建前设置）
    _set_app_user_model_id()

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
    # 窗口/任务栏图标：webview.start(icon=) 官方入口（2026-09-02 fix——
    # 此前 loaded 回调 hack 在 pythonnet 未预加载 System.Drawing 时静默失败，
    # 任务栏仍显示 python.exe 图标；start() 在窗口创建前应用，任务栏正确）
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _ico = os.path.join(root_dir, "icon.ico")
    _start_kwargs = {}
    if os.path.isfile(_ico):
        _start_kwargs["icon"] = _ico
        # 任务栏大图标（WM_SETICON）：start(icon=) 只覆盖标题栏小图标
        window.events.loaded += lambda: _apply_taskbar_icon(window, _ico)
    # 窗口关闭 → 停服务（线程 is daemon，但显式置位避免 uvicorn 在关闭竞态中继续收请求）
    window.events.closed += lambda: setattr(server, "should_exit", True)
    webview.start(**_start_kwargs)
    server.should_exit = True


def main() -> None:
    run_embedded()


if __name__ == "__main__":
    main()
