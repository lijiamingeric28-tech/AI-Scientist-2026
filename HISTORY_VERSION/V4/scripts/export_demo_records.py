# -*- coding: utf-8 -*-
"""导出 18 组演示查询的全部提取记录（值+单位+来源+置信度），供逐性质人工审核。

输出：docs/demo-query-analysis/records_dump.txt（全部记录）
      docs/demo-query-analysis/summary.json（每任务统计）
"""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

conn = sqlite3.connect("web/data/tasks.db")
cur = conn.cursor()

# 18 组演示查询的 query 前缀（最新一批，created_at 2026-09-01）
cur.execute("""
    SELECT task_id, query, created_at, state_json FROM tasks
    WHERE created_at >= '2026-09-01' AND replay_of IS NULL
    ORDER BY created_at
""")
rows = cur.fetchall()

OUT_DIR = Path("docs/demo-query-analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)

summary = {}
dump_lines = []
for tid, query, created, state_json in rows:
    if not state_json:
        continue
    st = json.loads(state_json)
    fo = st.get("final_output")
    if isinstance(fo, str):
        fo = json.loads(fo)
    if not fo:
        continue
    recs = fo.get("records") or []
    src_titles = {s.get("source_id"): s.get("title", "") for s in fo.get("sources", [])}
    figs = fo.get("figure_evidence") or []
    if isinstance(figs, dict):
        figs = figs.get("figures") or figs.get("items") or []
    # 质量分
    overall = None
    level = None
    qr = fo.get("quality_report") or {}
    rs = qr.get("report_state") or {}
    def find(o, key):
        res = []
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key:
                    res.append(v)
                res += find(v, key)
        elif isinstance(o, list):
            for i in o:
                res += find(i, key)
        return res
    scores = find(rs, "overall_score")
    if scores:
        overall = max(scores)
    # 数据集级 quality_scoring 优先
    qs = rs.get("quality") or {}
    qs2 = qs.get("quality_scoring") or {}
    if qs2.get("overall_score") is not None:
        overall = qs2["overall_score"]
        level = qs2.get("quality_level")

    simbad = fo.get("simbad_info") or {}
    by_field = defaultdict(list)
    for r in recs:
        by_field[r.get("field_name")].append(r)

    summary[tid[:8]] = {
        "query": query,
        "otype": simbad.get("otype") or simbad.get("object_type") or "?",
        "main_id": simbad.get("main_id") or "?",
        "n_records": len(recs),
        "n_sources": len(fo.get("sources", [])),
        "n_figs": len(figs) if isinstance(figs, list) else 0,
        "overall_score": overall,
        "quality_level": level,
        "fields": {k: len(v) for k, v in by_field.items()},
    }

    dump_lines.append(f"\n{'='*80}")
    dump_lines.append(f"QUERY: {query}  [{tid[:8]}]")
    dump_lines.append(f"otype={simbad.get('otype')} main_id={simbad.get('main_id')} "
                      f"records={len(recs)} figs={len(figs) if isinstance(figs, list) else 0} "
                      f"score={overall} level={level}")
    for fn, rl in sorted(by_field.items(), key=lambda x: -len(x[1])):
        dump_lines.append(f"\n  [{fn}] x{len(rl)}")
        for r in rl:
            src = r.get("source_id", "")
            title = src_titles.get(src, src)
            val = str(r.get("field_value", ""))[:38]
            unit = r.get("field_unit", "")
            conf = r.get("confidence") or r.get("extraction_confidence") or ""
            page = ""
            prov = r.get("provenance") or {}
            if isinstance(prov, dict):
                page = prov.get("page") or prov.get("page_num") or ""
            line = f"      {val:40} {unit:12} conf={conf} p{page}  <- {src} {title[:45]}"
            dump_lines.append(line)

with open(OUT_DIR / "records_dump.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(dump_lines))
with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)

print(f"{len(summary)} tasks exported")
for k, v in summary.items():
    print(f"  {k} | {v['query'][:26]:28} | recs={v['n_records']:3} figs={v['n_figs']:3} score={v['overall_score']} | {v['fields']}")
