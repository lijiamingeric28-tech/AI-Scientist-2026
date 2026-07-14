"""
extraction_quality.py — V2.3 新增: grounded_data 提取质量检查

检查提取子图产出的 grounded_data 中各条 record 的提取质量:
  - trace_id 是否存在
  - provenance.page 是否存在
  - provenance.bbox 是否存在
  - extraction_method 是否合法 (llm_text / llm_table)
  - record_id 是否匹配格式 {source_id}_{field_name}_{n}
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

_VALID_EXTRACTION_METHODS = {"llm_text", "llm_table"}


def check_extraction_quality(records: list[dict]) -> dict[str, Any]:
    """检查 grounded_data records 的提取质量。

    Returns: {score, total_records, missing_trace_id, missing_page,
              missing_bbox, bad_extraction_method, bad_record_id,
              trace_id_coverage, provenance_coverage,
              extraction_method_distribution, issues, summary}
    """
    total = len(records)
    if total == 0:
        return {
            "score": 1.0, "total_records": 0,
            "missing_trace_id": 0, "missing_page": 0, "missing_bbox": 0,
            "bad_extraction_method": 0, "bad_record_id": 0,
            "trace_id_coverage": 1.0, "provenance_coverage": 1.0,
            "extraction_method_distribution": {},
            "issues": [], "summary": "无数据记录。",
        }

    missing_trace_id = 0
    missing_page = 0
    missing_bbox = 0
    bad_extraction_method = 0
    bad_record_id = 0
    method_counts: dict[str, int] = {}

    for r in records:
        # trace_id 检查
        if not r.get("trace_id"):
            missing_trace_id += 1

        # provenance 检查
        prov = r.get("provenance")
        if not prov or not isinstance(prov, dict):
            missing_page += 1
            missing_bbox += 1
        else:
            if prov.get("page") is None:
                missing_page += 1
            if not prov.get("bbox") or not isinstance(prov.get("bbox"), list) or len(prov.get("bbox", [])) != 4:
                missing_bbox += 1

        # extraction_method 检查
        em = r.get("extraction_method", "")
        if em:
            method_counts[em] = method_counts.get(em, 0) + 1
            if em not in _VALID_EXTRACTION_METHODS:
                bad_extraction_method += 1

        # record_id 格式检查: {source_id}_{field_name}_{n}
        rid = r.get("record_id", "")
        sid = r.get("source_id", "")
        fn = r.get("field_name", "")
        if rid and sid and fn:
            # 标准化比较: DOI 中的 / . 在 record_id 中常被替换为 _
            def _norm(s):
                return s.replace("/", "_").replace(".", "_")
            expected_prefix = f"{_norm(sid)}_{fn}_"
            if not _norm(rid).startswith(expected_prefix):
                bad_record_id += 1

    # 加权评分
    score = 1.0 - (
        0.25 * (missing_trace_id / total) +
        0.20 * (missing_page / total) +
        0.15 * (missing_bbox / total) +
        0.20 * (bad_extraction_method / total) +
        0.20 * (bad_record_id / total)
    )
    score = max(0.0, min(1.0, round(score, 4)))

    # 覆盖率
    trace_id_coverage = 1.0 - missing_trace_id / total
    provenance_coverage = 1.0 - (missing_page + missing_bbox) / (2 * total)

    issues = []
    if missing_trace_id > 0:
        issues.append(f"{missing_trace_id}/{total} records missing trace_id")
    if missing_page > 0:
        issues.append(f"{missing_page}/{total} records missing provenance.page")
    if missing_bbox > 0:
        issues.append(f"{missing_bbox}/{total} records missing provenance.bbox")
    if bad_extraction_method > 0:
        issues.append(f"{bad_extraction_method}/{total} records with invalid extraction_method")
    if bad_record_id > 0:
        issues.append(f"{bad_record_id}/{total} records with bad record_id format")

    logger.info("[ExtractionQuality] score=%.2f, trace_id=%.0f%%, page=%.0f%%, bbox=%.0f%%, em_valid=%d/%d, rid_valid=%d/%d",
                score, trace_id_coverage * 100,
                (1 - missing_page / total) * 100 if total else 0,
                (1 - missing_bbox / total) * 100 if total else 0,
                total - bad_extraction_method, total,
                total - bad_record_id, total)

    return {
        "score": score,
        "total_records": total,
        "missing_trace_id": missing_trace_id,
        "missing_page": missing_page,
        "missing_bbox": missing_bbox,
        "bad_extraction_method": bad_extraction_method,
        "bad_record_id": bad_record_id,
        "trace_id_coverage": round(trace_id_coverage, 4),
        "provenance_coverage": round(provenance_coverage, 4),
        "extraction_method_distribution": method_counts,
        "issues": issues,
        "summary": "; ".join(issues) if issues else "提取质量良好。",
    }
