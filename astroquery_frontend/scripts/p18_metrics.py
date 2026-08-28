"""P18 消融对照指标提取（真实数据，零编造）

用法：
  python scripts/p18_metrics.py \
    --raw output/p18_ablation/quality_off_final_output.json \
    --cleaned output/m45_real_run/grounded_data_20260824_195658.json \
    --quality-summary output/m45_real_run/quality_summary_20260824_195658.json \
    --out output/p18_ablation/p18_metrics.json

--raw 可省略：消融运行完成后补充；--cleaned 必填（本作品基准 m45_real_run）。

输出：控制台 markdown 对比表 + --out JSON（raw/cleaned 各自 analyze 结果 + 质量管线摘要）。
"""
import argparse
import json
import re
from collections import Counter

# 单位感知的宽松可行域（仅用于发现"明显异常值"，候选请人工复核后引用）
RANGES = {
    "age": {"log(yr)": (7.0, 10.0), "Myr": (0.0, 1e4), "yr": (1e6, 1e13), "10^6 yr": (0.0, 1e4)},
    "distance": {"pc": (0.1, 1e4)},
    "dist_modulus": {"mag": (0.0, 15.0)},
    "parallax": {"mas": (0.01, 1e3)},
    "fe_h": {"dex": (-3.0, 2.0), "log(Sun)": (-3.0, 2.0)},
}

# 值/单位脏模式（单位应已提取分离，值本身残留单位/区间/分隔符 = 脏格式）
PATTERNS = {
    "range_dash": r"\d+\s*-\s*\d+",          # 70-100 / 70000000-125000000
    "embedded_unit": r"\d+_[a-zA-Z]+",       # 100_myr
    "plusminus": r"(\+/-|±|_\+/-_|\+/-_)",   # 5.33_+/-_0.06 / 134.6 ± 3.1
    "log_form": r"log\s*\(",
    "to_range": r"_to_",
    "trailing_tilde": r"~",
}


def parse_first_number(v) -> float | None:
    """从字符串值中提取第一个数字（容忍 ±/区间——区间首值也取，由调用方判断模式）"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", v)
        if m:
            return float(m.group())
    return None


def classify_dirty(v, unit) -> dict:
    """返回该值的脏模式集合（可能多个）"""
    sv = str(v)
    hits = []
    for name, pat in PATTERNS.items():
        if re.search(pat, sv):
            hits.append(name)
    # 单位与值分离度：value 以字母结尾或含空格字母 = 单位未完全分离
    if re.search(r"\d+\.?\d*\s*[a-zA-Z][a-zA-Z]*\s*$", sv) and not re.search(r"[0-9]$", sv):
        hits.append("unit_tail")
    return {h for h in hits}


def analyze(data: dict) -> dict:
    records = data.get("records") or []
    sources = data.get("sources") or []
    out: dict = {}
    out["n_records"] = len(records)
    out["n_sources"] = len(sources)
    out["source_type"] = dict(Counter(s.get("source_type") for s in sources))
    out["field_counts"] = dict(Counter(r.get("field_name") for r in records))
    out["extraction_method"] = dict(Counter(r.get("extraction_method") for r in records))

    # 单位混杂：全部 unit 集合（按 field）；以及按 (source,field) 内单位是否相对一致
    units_by_field: dict[str, Counter] = {}
    for r in records:
        units_by_field.setdefault(r.get("field_name"), Counter())[r.get("field_unit")] += 1
    out["units_by_field"] = {k: dict(v) for k, v in units_by_field.items()}
    per_src_field: dict[tuple, set] = {}
    for r in records:
        per_src_field.setdefault((r.get("source_id"), r.get("field_name")), set()).add(r.get("field_unit"))
    mismatch = [
        {"source_id": s, "field_name": f, "units": sorted(u)}
        for (s, f), u in per_src_field.items() if len(u) > 1
    ]
    out["n_src_field_unit_mismatch"] = len(mismatch)
    out["mismatch_details"] = mismatch

    # 脏模式统计 + 异常值候选
    dirty: Counter = Counter()
    dirty_examples: dict = {}
    oob = []
    for r in records:
        f, v, u = r.get("field_name"), r.get("field_value"), r.get("field_unit")
        pats = classify_dirty(v, u)
        for p in pats:
            dirty[p] += 1
            dirty_examples.setdefault(p, []).append(
                {"source_id": r.get("source_id"), "field_name": f, "value": str(v),
                 "unit": u, "page": (r.get("provenance") or {}).get("page")})
        # 越界（仅对纯数字值 + 该 field/unit 有定义域）
        rng = RANGES.get(f, {}).get((u or "").lower() if isinstance((u or ""), str) else "")
        if rng and not pats:
            num = parse_first_number(v)
            if num is not None and not (rng[0] <= num <= rng[1]):
                oob.append({"source_id": r.get("source_id"), "field_name": f, "value": str(v),
                            "unit": u, "page": (r.get("provenance") or {}).get("page")})
    out["dirty_patterns"] = dict(sorted(dirty.items(), key=lambda kv: -kv[1]))
    out["dirty_examples"] = {k: v[:3] for k, v in dirty_examples.items()}
    out["oob_candidates"] = oob  # 人工复核后引用；不自动进入 P18

    # bbox / 溯源覆盖
    pb = Counter((r.get("provenance") or {}).get("bbox_source") for r in records)
    out["bbox_source"] = dict(pb)
    out["provenance_coverage"] = {
        "page": sum(1 for r in records if (r.get("provenance") or {}).get("page") is not None),
        "bbox": sum(1 for r in records if (r.get("provenance") or {}).get("bbox")),
        "trace_id": sum(1 for r in records if r.get("trace_id")),
        "total": len(records),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="消融运行 final_output / grounded_data JSON（对照侧）")
    ap.add_argument("--cleaned", required=True, help="m45_real_run grounded_data JSON（本作品侧）")
    ap.add_argument("--quality-summary", default="", help="m45_real_run quality_summary JSON")
    ap.add_argument("--out", default="output/p18_ablation/p18_metrics.json")
    args = ap.parse_args()

    cleaned = analyze(json.load(open(args.cleaned, encoding="utf-8")))
    result = {"cleaned": cleaned, "raw": None}
    if args.raw:
        result["raw"] = analyze(json.load(open(args.raw, encoding="utf-8")))
    if args.quality_summary:
        result["quality_pipeline"] = json.load(open(args.quality_summary, encoding="utf-8"))

    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    def row(k, side):
        v = (side or {}).get(k) if side else None
        return v

    print("### P18 指标（来源：真实运行产物）\n")
    c, r = result["cleaned"], result["raw"]
    print("| 指标 | 本作品(cleaned) | 对照(raw) |")
    print("|---|---|---|")
    for k in ["n_records", "n_sources", "provenance_coverage", "dirty_patterns", "oob_candidates",
              "units_by_field", "field_counts"]:
        print(f"| {k} | {json.dumps(c.get(k), ensure_ascii=False)} | {json.dumps((r or {}).get(k), ensure_ascii=False)} |")
    if "quality_pipeline" in result:
        qp = result["quality_pipeline"]
        print("\n### 质量管线处理统计（m45_real_run quality_summary）")
        print(json.dumps(qp.get("issues_summary"), ensure_ascii=False),
              json.dumps(qp.get("processing_statistics"), ensure_ascii=False))
    print(f"\n[P18] saved -> {args.out}")


if __name__ == "__main__":
    main()
