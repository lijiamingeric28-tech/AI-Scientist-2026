"""AstroQuery AI 命令行入口（标准 CLI）

用法::

    astroquery-ai "M31 的距离是多少？"          # 安装后终端命令
    python -m astroquery_ai "M31 的距离是多少？" # 未安装时
    python -m astroquery_ai "M31 的距离" --pdf ./my_paper.pdf
    python -m astroquery_ai "M31 的距离" -o ./out/result.json

输出：完整 final_output 写入 JSON 文件，摘要打印到终端。
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

from astroquery_ai import run_pipeline
from astroquery_ai.logger import setup_logging

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "output"


def parse_args():
    p = argparse.ArgumentParser(
        description="AstroQuery AI — 天文数据检索与提取流水线",
    )
    p.add_argument(
        "query", nargs="?", default=None,
        help="自然语言查询，例如 'M31 的距离是多少？'；省略则进入交互模式",
    )
    p.add_argument(
        "--pdf", action="append", default=[], metavar="PATH",
        help="手动上传的 PDF 路径，可重复指定",
    )
    p.add_argument(
        "-o", "--output", default=None, metavar="PATH",
        help=f"输出 JSON 路径（默认 {DEFAULT_OUT_DIR}/result_<query_id>.json）",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="打开 DEBUG 日志")
    return p.parse_args()


def prompt_interactive(preset_pdfs):
    """
    无参数启动时的交互引导。

    只负责收集"查询语句"和"可选 PDF"两项；
    天体名称/性质的追问由子图 1 在流水线内部完成（HITL interrupt）。
    """
    print()
    print("═" * 60)
    print("  AstroQuery AI — 交互模式")
    print("  (直接回车退出；也可用 astroquery-ai \"你的问题\" 跳过本步)")
    print("═" * 60)

    query = input("\n请输入你的天文查询：").strip()
    if not query:
        print("未输入内容，已退出。")
        return None, None

    pdfs = list(preset_pdfs)
    raw = input(
        "手动补充 PDF 路径（可选，多个用空格分隔，直接回车跳过）：\n> "
    ).strip()
    if raw:
        # 支持带引号的路径（含空格时）
        import shlex
        try:
            pdfs.extend(shlex.split(raw))
        except ValueError:
            pdfs.extend(raw.split())

    return query, pdfs


def _force_utf8_stdio() -> None:
    """Windows GBK 控制台修复：强制 stdout/stderr 用 UTF-8。

    程序内大量 print 含非 GBK 字符（✓ ✗ ↻ 📄 等），
    GBK 控制台直接 UnicodeEncodeError 崩溃（clarification 阶段实测炸过）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass  # 非 TextIOWrapper 环境（pytest 捕获等）无需处理


def main() -> int:
    _force_utf8_stdio()
    args = parse_args()
    setup_logging(verbose=args.verbose)
    log = logging.getLogger("cli")

    query = args.query
    raw_pdfs = list(args.pdf)

    # 无查询参数 -> 交互模式
    if not query:
        try:
            query, raw_pdfs = prompt_interactive(raw_pdfs)
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return 130
        if not query:
            return 0

    query_id = str(uuid.uuid4())

    # 手动 PDF 转绝对路径并校验
    extra_pdfs = []
    for raw in raw_pdfs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            log.error("PDF 不存在: %s", path)
            return 2
        extra_pdfs.append(str(path))

    try:
        state = run_pipeline(
            user_query=query,
            extra_pdfs=extra_pdfs,
            query_id=query_id,
        )
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130

    final_output = state.get("final_output") or {}

    # ── 写输出 ──
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = DEFAULT_OUT_DIR / f"result_{query_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    # ── 终端摘要 ──
    sources = final_output.get("sources", [])
    records = final_output.get("records", [])
    errors = state.get("error_log", []) or []

    print()
    print("═" * 60)
    print(f"  query_id       : {query_id}")
    print(f"  target_entity  : {state.get('target_entity')}")
    print(f"  schema_version : {final_output.get('schema_version')}")
    print(f"  sources        : {len(sources)}")
    print(f"  records        : {len(records)}")
    print(f"  paper_records  : {len(state.get('paper_records', []))}")
    print(f"  errors         : {len(errors)}")
    print(f"  output         : {out_path}")
    print("═" * 60)

    if errors:
        print("\n错误摘要：")
        for e in errors[:10]:
            print(f"  - [{e.get('node')}] {e.get('error')}")
        if len(errors) > 10:
            print(f"  ... 另有 {len(errors) - 10} 条")

    return 0


if __name__ == "__main__":
    sys.exit(main())
