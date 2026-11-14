"""Run the local application and its native window in one desktop process."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import threading
import time

HOST = "127.0.0.1"
WINDOW_SIZE = (1500, 940)
WINDOW_MIN = (1000, 650)


def window_geometry(work_width=None, work_height=None):
    width, height = WINDOW_SIZE
    maximize = False
    if work_width and work_height:
        width = min(width, max(1, work_width - 32))
        height = min(height, max(1, work_height - 64))
        maximize = (width, height) != WINDOW_SIZE
    return dict(width=width, height=height, maximized=maximize,
                min_size=(min(WINDOW_MIN[0], width), min(WINDOW_MIN[1], height)))


def desktop_geometry():
    if sys.platform == "win32":
        import ctypes
        from ctypes.wintypes import RECT
        work = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
            return window_geometry(work.right - work.left, work.bottom - work.top)
    return window_geometry()


def desktop_socket(host: str, port: int | None) -> socket.socket:
    """Pass the reserved socket directly to uvicorn, including when the preferred port is busy."""
    if port is not None and not 1024 <= port <= 65535:
        raise ValueError("桌面端口应在 1024 到 65535 之间")
    if port is None:
        start = int(os.environ.get("ASTROQUERY_PORT") or 8000)
        if not 1024 <= start <= 65535:
            raise ValueError("ASTROQUERY_PORT 应在 1024 到 65535 之间")
        ports = [*range(start, min(start + 11, 65536)), 0]
    else:
        ports = [port]
    for candidate in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, candidate))
            return sock
        except OSError:
            sock.close()
    raise RuntimeError(f"无法监听本机端口 {port or start}，请关闭占用该端口的程序或选择其他端口。")


def require_webview2():
    """Use the same Microsoft loader as pywebview to check the Windows browser runtime."""
    import ctypes
    import platform
    from webview.util import interop_dll_path

    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64" if sys.maxsize > 2**32 else "x86"
    dll = Path(interop_dll_path("win-" + arch)) / "WebView2Loader.dll"
    get_version = ctypes.WinDLL(str(dll)).GetAvailableCoreWebView2BrowserVersionString
    get_version.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    get_version.restype = ctypes.c_long
    value = ctypes.c_void_p()
    try:
        if get_version(None, ctypes.byref(value)) != 0 or not value.value:
            raise RuntimeError("此电脑缺少 Microsoft Edge WebView2 Runtime。请按压缩包内的《使用说明》安装后重新打开。")
    finally:
        if value.value:
            release = ctypes.windll.ole32.CoTaskMemFree
            release.argtypes = [ctypes.c_void_p]
            release.restype = None
            release(value)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AstroQueryAI.Desktop")


def run_embedded(host: str = HOST, port: int | None = None) -> None:
    import uvicorn
    import webview
    from astroquery_ai.runtime.paths import data_root, resource_root
    from .http import create_app

    if sys.platform == "win32":
        require_webview2()
    with desktop_socket(host, port) as sock:
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            create_app(), host=host, port=port, log_level="warning", use_colors=False,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="astroquery-web")
        thread.start()
        try:
            deadline = time.monotonic() + 30
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                thread.join(0.08)
            if not server.started:
                raise RuntimeError("本机查询服务未能启动，请检查数据目录是否可写或已被其他实例使用。")
            window = webview.create_window(
                "AstroQuery AI", f"http://{host}:{port}",
                **desktop_geometry(),
            )
            window.events.closed += lambda: setattr(server, "should_exit", True)
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.start(
                gui="edgechromium" if sys.platform == "win32" else None,
                private_mode=False, storage_path=str(data_root() / "webview"),
                icon=str(resource_root() / "desktop/icon.ico"),
            )
        finally:
            server.should_exit = True
            thread.join()


def main() -> None:
    run_embedded()


if __name__ == "__main__":
    main()
