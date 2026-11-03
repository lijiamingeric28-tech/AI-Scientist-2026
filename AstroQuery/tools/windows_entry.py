"""Windows desktop and isolated parser entry for the portable distribution."""
import sys

from astroquery_ai.api.launcher import main

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if sys.platform != "win32" or sys.stderr is not None or "--parser-worker" in sys.argv:
            raise
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), "AstroQuery AI · 启动提示", 0x10)
        raise SystemExit(1) from error
