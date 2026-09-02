# -*- coding: utf-8 -*-
"""清除历史任务：只保留 08-28 M45 定稿版（1e6c3e2e），其余 36 条全部删除。"""
import io
import sys

import requests

BASE = "http://127.0.0.1:8000"

KEEP = {"1e6c3e2e-9e5e-4248-a6b8-5fd3faad274c"}  # 08-28 M45 定稿版


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    resp = requests.get(f"{BASE}/api/tasks?limit=200", timeout=30)
    rows = resp.json().get("items", [])
    history = [t for t in rows if t["created_at"] < "2026-09-01"]
    to_delete = [t for t in history if t["task_id"] not in KEEP]
    print(f"历史任务 {len(history)} 条，保留 {len(history) - len(to_delete)} 条，删除 {len(to_delete)} 条")
    for t in history:
        mark = "KEEP" if t["task_id"] in KEEP else "del "
        print(f"  {mark} {t['created_at'][:10]} {t['query'][:36]:38} {t['task_id'][:8]}")
    if not to_delete:
        print("无任务可删")
        return
    ids = [t["task_id"] for t in to_delete]
    # 分批删（每次 20 个）
    for i in range(0, len(ids), 20):
        batch = ids[i:i + 20]
        r = requests.post(f"{BASE}/api/tasks/batch-delete", json={"task_ids": batch}, timeout=300)
        results = r.json().get("results", [])
        ok = sum(1 for x in results if x.get("deleted"))
        print(f"  批 {i // 20 + 1}: {ok}/{len(batch)} 删除成功")
        for x in results:
            if not x.get("deleted"):
                print(f"    失败: {x['task_id'][:8]} {x.get('reason')}")


if __name__ == "__main__":
    main()
