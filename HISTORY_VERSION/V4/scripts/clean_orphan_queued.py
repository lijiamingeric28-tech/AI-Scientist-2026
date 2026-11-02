# -*- coding: utf-8 -*-
"""一次性脚本：删除后端重启后遗留的 queued 孤儿任务（executor 内存队列已丢，DB 无人消费）。"""
import io
import sys

import requests

BASE = "http://127.0.0.1:8000"


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    resp = requests.get(f"{BASE}/api/tasks?limit=100", timeout=30)
    rows = resp.json().get("items", [])
    queued = [t for t in rows if t.get("status") == "queued"]
    print(f"queued 孤儿 {len(queued)} 条")
    if not queued:
        return
    r = requests.post(f"{BASE}/api/tasks/batch-delete",
                      json={"task_ids": [t["task_id"] for t in queued]}, timeout=60)
    ok = sum(1 for x in r.json().get("results", []) if x.get("deleted"))
    print(f"删除 {ok}/{len(queued)}")
    remaining = requests.get(f"{BASE}/api/tasks?limit=100", timeout=30).json().get("items", [])
    print("剩余非 completed:", [(t['status'], t['query'][:16]) for t in remaining
                                if t['status'] != 'completed'] or "无")


if __name__ == "__main__":
    main()
