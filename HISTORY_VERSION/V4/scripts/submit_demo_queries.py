# -*- coding: utf-8 -*-
"""评审演示查询批量提交：POST /api/tasks 全部排队（executor 并发=1 自动串行）。

用法:
    python scripts/submit_demo_queries.py            # 提交全部 18 组
    python scripts/submit_demo_queries.py --list     # 只打印将提交的查询

幂等说明：每次运行都会新建任务（不做去重），如需重跑请先确认队列为空。
"""
import argparse
import io
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"

QUERIES = [
    # ── A. TAXONOMY OF STARS ──
    "参宿四的半径、质量和表面温度",
    "大角星的距离、金属丰度和有效温度",
    "天狼星B的质量、有效温度、表面重力和冷却年龄",
    "蟹状星云脉冲星的自转周期、周期导数、特征年龄和表面磁场",
    "天鹅座X-1的轨道周期、致密天体质量和伴星质量",
    "参宿七的光度、有效温度和星风强度",
    "米拉的光变周期、变幅和质量损失率",
    # ── B. SETS OF STARS ──
    "昴星团(M45)的年龄、距离和金属丰度",
    "大陵五的轨道周期、掩食深度和质量比",
    "半人马座ω的中心速度弥散、总质量和金属丰度",
    "天鹅座OB2星协的成员星数量、OB星数量和运动学年龄",
    # ── C. TAXONOMY OF GALAXIES ──
    "M31 的距离、视星等和恒星质量",
    "M87 的中央黑洞质量、爱丁顿比和6cm射电流量",
    "大麦哲伦云的距离、恒星形成率和气体金属丰度",
    "3C 273 的红移、视星等、绝对星等和X射线光子谱指数",
    # ── D. SETS OF GALAXIES ──
    "后发座星系团的速度弥散、X射线温度和M500质量",
    "室女座星系团的距离、成员星系数量和X射线光度",
    "HCG 92 的成员星系数、动力学质量和HI缺陷度",
]

SLUGS = [
    "betelgeuse", "arcturus", "sirius-b", "crab-pulsar", "cyg-x1",
    "rigel", "mira", "m45", "algol", "omega-centauri", "cygnus-ob2",
    "m31", "m87", "lmc", "3c273", "coma", "virgo", "hcg92",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只打印查询不提交")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if args.list:
        for i, q in enumerate(QUERIES, 1):
            print(f"{i:2d}. {q}")
        return

    created = []
    for q in QUERIES:
        resp = requests.post(f"{args.base}/api/tasks", json={"query": q}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        created.append((q, body["task_id"], body["status"]))
        print(f"OK  {body['status']:8} {q}  ->  {body['task_id'][:8]}")

    print(f"\n共提交 {len(created)} 组，全部排队（executor 并发=1 串行执行）")
    with open("_demo_submitted.json", "w", encoding="utf-8") as f:
        json.dump(created, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
