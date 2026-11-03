"""Compatibility import; implementation lives in the CLI adapter."""
from .api.cli import main, _until_idle

if __name__ == "__main__":
    raise SystemExit(main())
