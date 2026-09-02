# -*- coding: utf-8 -*-
"""评审演示第二批提交：10 重查（删坏性质）+ 2 常规新增 + 8 小众新增 = 20 组。

用法:
    python scripts/submit_demo_queries_round2.py
"""
import io
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"

QUERIES = [
    # ── B 组：删坏性质重查（10）──
    "Pollux的质量、半径、表面温度和光谱型",
    "delta Cephei 的光变周期、距离和金属丰度",
    "比邻星的距离、视差和自行",
    "天狼星B的质量、表面重力和冷却年龄",
    "天鹅座X-1的轨道周期和致密天体质量",
    "参宿七的光度和有效温度",
    "3C 273 的红移、绝对星等和X射线光子谱指数",
    "大麦哲伦云的恒星形成率和气体金属丰度",
    "M31 的距离和恒星质量",
    "蟹状星云脉冲星的自转周期、周期导数和特征年龄",
    # ── C 组：常规新增（2）──
    "环状星云M57的膨胀速度、电子密度和中心星温度",
    "NGC 4151 的黑洞质量、Hβ发射线半高全宽和X射线光子谱指数",
    # ── D 组：小众专业性质新增（8）──
    "HD 209458b 的轨道周期、行星质量、行星半径和凌星深度",
    "SN 2011fe 的Δm15衰减率、峰值绝对星等和stretch参数",
    "Fornax A（NGC 1316）的射电功率、射电光谱指数和FR分类",
    "M15 的King聚集度、中心面亮度和核心半径",
    "Hercules X-1 的自转周期、轨道周期和爆发重现时间",
    "SS Cygni 的轨道周期、爆发周期和超周期长度",
    "Vela 脉冲星的色散量、自转突跳次数和旋转量",
    "常陈一（α² CVn）的磁场强度和自转周期",
]


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    created = []
    for q in QUERIES:
        resp = requests.post(f"{BASE}/api/tasks", json={"query": q}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        created.append((q, body["task_id"], body["status"]))
        print(f"OK  {body['status']:8} {q[:40]:42} -> {body['task_id'][:8]}")
    print(f"\n共提交 {len(created)} 组，全部排队（executor 并发=1 串行执行）")
    with open("_demo_submitted_round2.json", "w", encoding="utf-8") as f:
        json.dump(created, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
