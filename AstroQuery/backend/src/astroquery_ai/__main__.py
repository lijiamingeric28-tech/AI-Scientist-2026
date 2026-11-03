"""`python -m astroquery_ai` 入口 — 与安装后的 astroquery-ai 命令等价。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
