# -*- coding: utf-8 -*-
"""清除今天创建的弃用任务（放弃组 + 已被重查版取代的旧版）。

删除前需已备份 tasks.db（docs/demo-query-analysis/backup/）。
"""
import io
import sys

import requests

BASE = "http://127.0.0.1:8000"

# 按 query 精确匹配删除（今天创建的）
DEPRECATED_QUERIES = [
    # ── 放弃组（13）──
    "米拉的光变周期、变幅和质量损失率",
    "大陵五的轨道周期、掩食深度和质量比",
    "室女座星系团的距离、成员星系数量和X射线光度",
    "HCG 92 的成员星系数、动力学质量和HI缺陷度",
    "天鹅座OB2星协的成员星数量、OB星数量和运动学年龄",
    "M15 的King聚集度、中心面亮度和核心半径",
    "环状星云M57的膨胀速度、电子密度和中心星温度",
    "SS Cygni 的轨道周期、爆发周期和超周期长度",
    "Vela 脉冲星的色散量、自转突跳次数和旋转量",
    "3C 31 的射电功率、射电光谱指数和FR分类",
    "常陈一（α² CVn）的磁场强度和自转周期",
    "Fornax A（NGC 1316）的射电功率、射电光谱指数和FR分类",
    # ── 旧版被取代（14）──
    "天狼星B的质量、有效温度、表面重力和冷却年龄",
    "天鹅座X-1的轨道周期、致密天体质量和伴星质量",
    "参宿七的光度、有效温度和星风强度",
    "蟹状星云脉冲星的自转周期、周期导数、特征年龄和表面磁场",
    "蟹状星云脉冲星的自转周期、周期导数和特征年龄",
    "大麦哲伦云的距离、恒星形成率和气体金属丰度",
    "M31 的距离、视星等和恒星质量",
    "M31 的距离和恒星质量",
    "3C 273 的红移、视星等、绝对星等和X射线光子谱指数",
    "3C 273 的红移、绝对星等和X射线光子谱指数",
    "3C 273 的绝对星等",
    "HD 209458b 的轨道周期、行星质量、行星半径和凌星深度",
    "SN 2011fe 的Δm15衰减率、峰值绝对星等和stretch参数",
    "Hercules X-1 的自转周期、轨道周期和爆发重现时间",
]


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    resp = requests.get(f"{BASE}/api/tasks?limit=100", timeout=30)
    rows = resp.json().get("items", [])
    to_delete = []
    for t in rows:
        q = t.get("query", "")
        if q in DEPRECATED_QUERIES:
            to_delete.append((t["task_id"], q, t["status"]))
    print(f"匹配到 {len(to_delete)}/{len(DEPRECATED_QUERIES)} 个弃用任务")
    for tid, q, st in to_delete:
        print(f"  {st:10} {q[:36]:38} {tid[:8]}")
    # 未匹配的查询
    matched = {q for _, q, _ in to_delete}
    for q in DEPRECATED_QUERIES:
        if q not in matched:
            print(f"  !! 未找到: {q[:40]}")
    if not to_delete:
        print("无任务可删")
        return
    # 删除（排除运行中/排队中的）
    ids = [tid for tid, q, st in to_delete if st not in ("running", "queued")]
    r = requests.post(f"{BASE}/api/tasks/batch-delete", json={"task_ids": ids}, timeout=120)
    results = r.json().get("results", [])
    ok = sum(1 for x in results if x.get("deleted"))
    print(f"\nbatch-delete: {ok}/{len(ids)} 删除成功")
    for x in results:
        if not x.get("deleted"):
            print(f"  失败: {x['task_id'][:8]} {x.get('reason')}")


if __name__ == "__main__":
    main()
