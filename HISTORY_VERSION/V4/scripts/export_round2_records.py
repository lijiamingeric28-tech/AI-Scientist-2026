# -*- coding: utf-8 -*-
"""导出第二批已完成任务的记录，供逐性质验收。"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

conn = sqlite3.connect("web/data/tasks.db")
cur = conn.cursor()

cur.execute("""
    SELECT task_id, query, state_json FROM tasks
    WHERE created_at >= '2026-09-01T09:20' AND status='completed' AND replay_of IS NULL
    ORDER BY completed_at
""")
rows = cur.fetchall()

OUT_DIR = Path("docs/demo-query-analysis")
dump = []
summary = {}
for tid, query, sj in rows:
    if not sj:
        continue
    st = json.loads(sj)
    fo = st.get("final_output")
    if isinstance(fo, str):
        fo = json.loads(fo)
    if not fo:
        continue
    recs = fo.get("records") or []
    src_titles = {s.get("source_id"): s.get("title", "") for s in fo.get("sources", [])}
    by_field = defaultdict(list)
    for r in recs:
        by_field[r.get("field_name")].append(r)
    simbad = fo.get("simbad_info") or {}
    summary[tid[:8]] = {
        "query": query,
        "otype": simbad.get("otype") or simbad.get("object_type") or "?",
        "n_records": len(recs),
        "fields": {k: len(v) for k, v in by_field.items()},
    }
    dump.append(f"\n{'='*80}")
    dump.append(f"QUERY: {query}  [{tid[:8]}] otype={simbad.get('otype')}")
    for fn, rl in sorted(by_field.items(), key=lambda x: -len(x[1])):
        dump.append(f"\n  [{fn}] x{len(rl)}")
        for r in rl:
            src = r.get("source_id", "")
            title = src_titles.get(src, src)
            val = str(r.get("field_value", ""))[:36]
            unit = r.get("field_unit", "")
            conf = r.get("confidence") or ""
            prov = r.get("provenance") or {}
            page = (prov.get("page") or prov.get("page_num") or "") if isinstance(prov, dict) else ""
            dump.append(f"      {val:38} {unit:10} conf={conf} p{page}  <- {src} {title[:40]}")

with open(OUT_DIR / "round2_records.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(dump))
with open(OUT_DIR / "round2_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
for k, v in summary.items():
    print(f"  {k} | {v['query'][:30]:32} | {v['otype']:6} | {v['fields']}")
print(len(summary), "tasks exported")
