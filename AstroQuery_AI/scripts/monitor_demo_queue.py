# -*- coding: utf-8 -*-
"""监控演示队列进度：轮询 /api/tasks，每 10 分钟写一次进度快照到 _demo_progress.log。

用法（后台）:
    python scripts/monitor_demo_queue.py
"""
import io
import json
import sys
import time
from datetime import datetime, timezone

import requests

BASE = "http://127.0.0.1:8000"
LOG = "_demo_progress.log"

QUERIES = [
    "参宿四", "大角星", "天狼星B", "蟹状星云脉冲星", "天鹅座X-1",
    "参宿七", "米拉", "昴星团(M45)", "大陵五", "半人马座ω",
    "天鹅座OB2", "M31", "M87", "大麦哲伦云", "3C 273",
    "后发座星系团", "室女座星系团", "HCG 92",
]


def fmt(ts: str) -> str:
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return ts[:16] or "?"


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    done = set()
    started_at = time.time()
    while True:
        try:
            resp = requests.get(f"{BASE}/api/tasks", timeout=30)
            tasks = resp.json()
            # tasks 可能是 dict 或 list，兼容
            rows = tasks if isinstance(tasks, list) else tasks.get("items") or tasks.get("tasks") or []
        except Exception as e:
            rows = []
            print(f"[{datetime.now().strftime('%H:%M:%S')}] poll FAIL {e}", flush=True)

        by_status: dict = {}
        for t in rows:
            st = t.get("status", "?")
            by_status.setdefault(st, 0)
            by_status[st] += 1
            if st == "completed" and t.get("query", "")[:20] not in done:
                done.add(t.get("query", "")[:20])
        # 当前运行/排队的是哪些
        active = [t for t in rows if t.get("status") in ("running", "queued")]
        active_q = [f"{t['query'][:18]}({t['status'][0]})" for t in active]

        line = (
            f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] "
            f"运行:{by_status.get('running',0)} 排队:{by_status.get('queued',0)} "
            f"完成:{by_status.get('completed',0)} 错误:{by_status.get('error',0)} "
            f"| 活跃: {', '.join(active_q[:3]) or '-'}"
        )
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

        if by_status.get("running", 0) == 0 and by_status.get("queued", 0) == 0:
            # 队列清空
            if by_status.get("completed", 0) >= 18:
                print("ALL DEMO QUERIES DONE", flush=True)
                return
            # 可能还有 error/cancelled
            print(f"QUEUE EMPTY: completed={by_status.get('completed',0)} "
                  f"error={by_status.get('error',0)} cancelled={by_status.get('cancelled',0)}", flush=True)
            if time.time() - started_at > 6 * 3600:
                return
        time.sleep(600)


if __name__ == "__main__":
    main()
