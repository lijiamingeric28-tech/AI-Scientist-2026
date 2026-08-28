"""P18 对照组 1：人工摘录 vs 系统提取 比对

用法：
  python scripts/p18_manual_compare.py \
    --manual  output/p18_ablation/manual_extraction.csv \
    --cleaned output/m45_real_run/grounded_data_20260824_195658.json \
    --out     output/p18_ablation/manual_compare.json

人工 CSV 列：seq, property, value, unit, source, page, quote, seconds_spent, note
  - property ∈ age/distance/dist_modulus/parallax/fe_h
  - source 填论文 bibcode 前缀（如 1999ApJ...523..328N，可比对系统 source_id）或 MWSC
  - value/unit 原样抄写，不换算

匹配：field_name==property；source 前缀匹配系统 source_id（paper source_id=bibcode，
database=SRC_DB_MWSC 由 MWSC 映射）。数值相对误差 <1% 或字符串一致 → 命中。
输出：命中明细 / 系统遗漏 / 系统覆盖度 / 回溯对照 / 人工耗时汇总。
"""
import argparse
import csv
import json
import os
import re
from datetime import datetime


def parse_num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", str(v))
    return float(m.group()) if m else None


def value_match(manual_val, sys_val) -> bool:
    mv, sv = parse_num(manual_val), parse_num(sys_val)
    if mv is not None and sv is not None and sv != 0:
        return abs(mv - sv) / abs(sv) < 0.01
    return str(manual_val).strip() == str(sys_val).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual", required=True)
    ap.add_argument("--cleaned", required=True)
    ap.add_argument("--out", default="output/p18_ablation/manual_compare.json")
    args = ap.parse_args()

    manual_rows = list(csv.DictReader(open(args.manual, encoding="utf-8-sig")))
    data = json.load(open(args.cleaned, encoding="utf-8"))
    records = data.get("records") or []
    by_source: dict[str, list] = {}
    for r in records:
        by_source.setdefault(r.get("source_id"), []).append(r)

    details = []
    matched, missed = 0, 0
    unmatched_manual_sources = []
    for row in manual_rows:
        prop = (row.get("property") or "").strip().lower()
        src_raw = (row.get("source") or "").strip()
        src_id = "SRC_DB_MWSC" if src_raw.upper() == "MWSC" else src_raw
        cands = [r for r in by_source.get(src_id, []) if (r.get("field_name") or "").lower() == prop]
        hit = None
        for r in cands:
            if value_match(row.get("value"), r.get("field_value")) and (row.get("unit") or "").lower().replace(" ", "") == str(r.get("field_unit") or "").lower().replace(" ", ""):
                hit = r
                break
        if hit is None:
            for r in cands:
                if value_match(row.get("value"), r.get("field_value")):
                    hit = r
                    break
        if src_id not in by_source and src_raw != "MWSC":
            unmatched_manual_sources.append(src_raw)
        details.append({
            "manual": {k: row.get(k) for k in ("seq", "property", "value", "unit", "source", "page", "quote", "seconds_spent", "note")},
            "matched_record": {
                "record_id": hit.get("record_id"), "field_value": hit.get("field_value"),
                "field_unit": hit.get("field_unit"), "page": (hit.get("provenance") or {}).get("page"),
                "bbox": (hit.get("provenance") or {}).get("bbox"),
                "extraction_method": hit.get("extraction_method"),
            } if hit else None,
        })
        matched += 1 if hit else 0

    missed = len(manual_rows) - matched
    total_seconds = sum(int(float(row["seconds_spent"] or 0)) for row in manual_rows if (row.get("seconds_spent") or "").strip())
    # 系统覆盖度：人工覆盖的 (source,property) 之外系统还有多少
    manual_pairs = {(r["source"].strip().upper() if r["source"].strip().upper() == "MWSC" else r["source"].strip(), r["property"].strip().lower()) for r in manual_rows}
    sys_pairs = {(r.get("source_id"), (r.get("field_name") or "").lower()) for r in records}
    extra_sys = len(sys_pairs - manual_pairs)

    result = {
        "manual_rows": len(manual_rows), "matched": matched, "missed": missed,
        "hit_rate": round(matched / len(manual_rows), 3) if manual_rows else None,
        "total_manual_seconds": total_seconds,
        "manual_recorded_unique_pairs": len(manual_pairs),
        "system_extra_pairs_beyond_manual": extra_sys,
        "details": details,
        "unmatched_manual_sources": sorted(set(unmatched_manual_sources)),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("### P18 对照组 1：人工 vs 系统 比对结果\n")
    print(f"- 人工摘录条数：{len(manual_rows)}；命中系统记录：{matched}；未命中：{missed}；命中率：{result['hit_rate']}")
    print(f"- 人工耗时：{total_seconds}s（约 {round(total_seconds/60, 1)} 分钟）")
    print(f"- 人工覆盖的唯一 (来源,性质) 对：{len(manual_pairs)}；系统额外覆盖：{extra_sys}")
    if unmatched_manual_sources:
        print(f"- 人工填写但未匹配到系统来源：{unmatched_manual_sources}（请核对 source 拼写）")
    print("\n| seq | 人工值 | 系统值 | 命中 | 人工页码 | 系统page/bbox |")
    print("|---|---|---|---|---|---|")
    for d in details:
        m, h = d["manual"], d["matched_record"]
        print(f"| {m['seq']} | {m['value']} {m['unit']} | "
              f"{h['field_value'] if h else '—'} {h['field_unit'] if h else ''} | "
              f"{'✔' if h else '✘'} | {m['page']} | "
              f"{h['page'] if h else '—'}/{(h or {}).get('bbox') or '—'} |")
    print(f"\n[P18] saved -> {args.out}")


if __name__ == "__main__":
    main()
