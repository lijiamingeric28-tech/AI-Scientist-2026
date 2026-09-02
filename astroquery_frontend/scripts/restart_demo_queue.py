# -*- coding: utf-8 -*-
"""一次性脚本：取消并删除当前演示队列（queued+running 的任务），然后重新提交 18 组。"""
import io
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"

sys.path.insert(0, "scripts")
from submit_demo_queries import QUERIES  # noqa: E402


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # 1. 收集非终态任务
    resp = requests.get(f"{BASE}/api/tasks?limit=100", timeout=30)
    rows = resp.json().get("items", [])
    active = [t for t in rows if t.get("status") in ("queued", "running")]
    print(f"非终态任务 {len(active)} 条")
    for t in active:
        print("  ", t["status"], t["query"][:24], t["task_id"][:8])

    # 2. 取消
    for t in active:
        r = requests.post(f"{BASE}/api/tasks/{t['task_id']}/cancel", timeout=30)
        print(f"cancel {t['task_id'][:8]} -> {r.status_code}")
    time.sleep(8)  # running 任务终态落库

    # 3. 批量删除
    ids = [t["task_id"] for t in active]
    r = requests.post(f"{BASE}/api/tasks/batch-delete", json={"task_ids": ids}, timeout=60)
    body = r.json()
    ok = sum(1 for x in body.get("results", []) if x.get("deleted"))
    print(f"batch-delete: {ok}/{len(ids)} 删除成功")

    # 4. 重新提交
    created = []
    for q in QUERIES:
        r = requests.post(f"{BASE}/api/tasks", json={"query": q}, timeout=30)
        r.raise_for_status()
        b = r.json()
        created.append((q, b["task_id"]))
        print(f"OK {b['status']:8} {q[:24]} -> {b['task_id'][:8]}")
    print(f"\n重新提交 {len(created)} 组，等待 auto-confirm runner 接管确认")


if __name__ == "__main__":
    main()
