# -*- coding: utf-8 -*-
"""最终 10 组新查询（删坏性质重查式新原版），提交到队列。"""
import io
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"

QUERIES = [
    "M31 的HI谱线宽度和恒星质量",
    "HD 209458b 的轨道周期、行星质量、行星半径",
    "蟹状星云脉冲星的自转周期",
    "SN 2011fe 的峰值绝对星等",
    "3C 273 的红移和绝对星等",
    "Hercules X-1 的自转周期和轨道周期",
    "NGC 6543 的膨胀速度、电子密度和中心星温度",
    "SS Cygni 的轨道周期和爆发间隔",
    "HCG 92 的速度弥散和成员星系数",
    "天鹅座OB2的距离和总质量",
]


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    created = []
    for q in QUERIES:
        r = requests.post(f"{BASE}/api/tasks", json={"query": q}, timeout=30)
        r.raise_for_status()
        b = r.json()
        created.append((q, b["task_id"], b["status"]))
        print(f"OK {b['status']:8} {q[:40]:42} -> {b['task_id'][:8]}")
    print(f"\n共提交 {len(created)} 组")
    with open("_demo_submitted_round3.json", "w", encoding="utf-8") as f:
        json.dump(created, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
