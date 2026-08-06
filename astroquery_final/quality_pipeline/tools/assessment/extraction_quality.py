"""
extraction_quality.py — V3.1: grounded_data 提取质量检查 (支持 database)

检查提取子图产出的 grounded_data 中各条 record 的提取质量:
  - Paper: trace_id + provenance.page + provenance.bbox + record_id 格式
  - Database: provenance.db_table + key_column + key_value + raw_column
  - extraction_method 合法性 (通用)
"""
from __future__ import annotations
from typing import Any
from ...tools.assessment.source_utils import is_database_record, provenance_is_complete
from ...utils.logger import get_logger
logger = get_logger(__name__)

# V3.1: 支持 V2 spec 中的所有 extraction_method 值 + database_query
_VALID_EXTRACTION_METHODS = {
    "vlm_pdf",        # VLM from paper text extraction (V2 spec §3.5)
    "vlm_text",       # VLM from text (V2 spec example §3.1)
    "llm_text",       # backward compat
    "llm_table",      # backward compat
    "database",       # Database query (backward compat)
    "csv_parsing",    # CSV file parsing (V2 spec §3.5)
    "database_query", # Database SQL/API query (V3.1)
}


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
    missing_db_prov = 0       # V3.1: database provenance 不完整的记录数
    bad_extraction_method = 0
    bad_record_id = 0
    n_database_records = 0    # V3.1: database 记录数
    # V1.1: entity 字段完整性
    missing_entity_type = 0
    missing_entity_name = 0
    method_counts: dict[str, int] = {}

    for r in records:
        is_db = is_database_record(r)

        # trace_id 检查 (仅 paper 记录)
        if not is_db:
            if not r.get("trace_id"):
                missing_trace_id += 1
        else:
            n_database_records += 1

        # V1.1: entity 字段检查
        if not r.get("entity_type"):
            missing_entity_type += 1
        if not r.get("entity_name"):
            missing_entity_name += 1

        # provenance 检查 (V3.1: 分支处理)
        if is_db:
            if not provenance_is_complete(r):
                missing_db_prov += 1
        else:
            prov = r.get("provenance")
            if not prov or not isinstance(prov, dict):
                missing_page += 1
                missing_bbox += 1
            else:
                if prov.get("page") is None:
                    missing_page += 1
                if not prov.get("bbox") or not isinstance(prov.get("bbox"), list) or len(prov.get("bbox", [])) != 4:
                    missing_bbox += 1

        # extraction_method 检查 (通用)
        em = r.get("extraction_method", "")
        if em:
            method_counts[em] = method_counts.get(em, 0) + 1
            if em not in _VALID_EXTRACTION_METHODS:
                bad_extraction_method += 1

        # V3.1: record_id 格式 (DB 记录跳过 paper 格式校验)
        if not is_db:
            rid = r.get("record_id", "")
            sid = r.get("source_id", "")
            en = r.get("entity_name", "")
            fn = r.get("field_name", "")
            if rid and sid and fn:
                def _norm(s):
                    return s.replace("/", "_").replace(".", "_").replace(" ", "_")
                expected = f"{_norm(sid)}_{_norm(en) if en else ''}{'_' if en else ''}{fn}_"
                if not _norm(rid).startswith(expected):
                    bad_record_id += 1

    # V3.1 加权评分: paper 和 database 分别计算, 按记录数加权
    n_paper = total - n_database_records

    paper_score = 1.0
    if n_paper > 0:
        paper_score = 1.0 - (
            0.15 * (missing_trace_id / n_paper) +
            0.10 * (missing_page / n_paper) +
            0.08 * (missing_bbox / n_paper) +
            0.10 * (bad_extraction_method / total) +
            0.10 * (bad_record_id / n_paper) +
            0.03 * (missing_entity_type / total) +
            0.03 * (missing_entity_name / total)
        )
        paper_score = max(0.0, min(1.0, paper_score))

    db_score = 1.0
    if n_database_records > 0:
        db_score = 1.0 - (
            0.33 * (missing_db_prov / n_database_records) +    # DB provenance (替代 trace_id+page+bbox)
            0.10 * (bad_extraction_method / total) +
            0.03 * (missing_entity_type / total) +
            0.03 * (missing_entity_name / total)
        )
        db_score = max(0.0, min(1.0, db_score))

    # 按记录数加权合并
    score = round(
        (paper_score * n_paper + db_score * n_database_records) / max(total, 1), 4
    )

    # 覆盖率
    trace_id_coverage = 1.0 - missing_trace_id / max(n_paper, 1)
    provenance_coverage = 1.0 - (missing_page + missing_bbox) / (2 * max(n_paper, 1)) if n_paper > 0 else 1.0
    db_provenance_coverage = 1.0 - missing_db_prov / max(n_database_records, 1) if n_database_records > 0 else 1.0

    issues = []
    if missing_trace_id > 0:
        issues.append(f"{missing_trace_id}/{n_paper} paper records missing trace_id")
    if missing_entity_type > 0:
        issues.append(f"{missing_entity_type}/{total} records missing entity_type")
    if missing_entity_name > 0:
        issues.append(f"{missing_entity_name}/{total} records missing entity_name")
    if missing_page > 0:
        issues.append(f"{missing_page}/{n_paper} paper records missing provenance.page")
    if missing_bbox > 0:
        issues.append(f"{missing_bbox}/{n_paper} paper records missing provenance.bbox")
    if missing_db_prov > 0:
        issues.append(f"{missing_db_prov}/{n_database_records} database records with incomplete provenance (db_table/key_column/key_value/raw_column)")
    if bad_extraction_method > 0:
        issues.append(f"{bad_extraction_method}/{total} records with invalid extraction_method")
    if bad_record_id > 0:
        issues.append(f"{bad_record_id}/{n_paper} paper records with bad record_id format")

    logger.info("[ExtractionQuality] score=%.2f, trace_id=%.0f%%, page=%.0f%%, bbox=%.0f%%, em_valid=%d/%d, rid_valid=%d/%d",
                score, trace_id_coverage * 100,
                (1 - missing_page / total) * 100 if total else 0,
                (1 - missing_bbox / total) * 100 if total else 0,
                total - bad_extraction_method, total,
                total - bad_record_id, total)

    # ── V2: per-entity extraction quality ──
    per_entity_scores: dict[str, float] = {}
    per_entity_issues: dict[str, list[str]] = {}
    entity_recs: dict[str, list[dict]] = {}
    for r in records:
        et = r.get("entity_type", "") or ""
        en = r.get("entity_name", "unknown")
        elabel = f"{et}:{en}" if et else en
        entity_recs.setdefault(elabel, []).append(r)

    for elabel, erecs in entity_recs.items():
        e_total = len(erecs)
        e_mt = sum(1 for r in erecs if not r.get("trace_id"))
        e_mp = sum(1 for r in erecs if not (r.get("provenance") or {}).get("page"))
        e_mb = sum(1 for r in erecs if not ((r.get("provenance") or {}).get("bbox") or [None]*4)[0:4])
        # Simplified per-entity score
        e_score = 1.0 - (0.4 * e_mt + 0.3 * e_mp + 0.3 * e_mb) / max(e_total, 1)
        per_entity_scores[elabel] = round(max(0.0, min(1.0, e_score)), 4)
        e_issues = []
        if e_mt > 0:
            e_issues.append(f"missing trace_id: {e_mt}/{e_total}")
        if e_mp > 0:
            e_issues.append(f"missing page: {e_mp}/{e_total}")
        if e_mb > 0:
            e_issues.append(f"missing bbox: {e_mb}/{e_total}")
        per_entity_issues[elabel] = e_issues

    return {
        "score": score,
        "total_records": total,
        "n_paper_records": n_paper,
        "n_database_records": n_database_records,
        "missing_trace_id": missing_trace_id,
        "missing_entity_type": missing_entity_type,
        "missing_entity_name": missing_entity_name,
        "missing_page": missing_page,
        "missing_bbox": missing_bbox,
        "missing_db_prov": missing_db_prov,
        "bad_extraction_method": bad_extraction_method,
        "bad_record_id": bad_record_id,
        "trace_id_coverage": round(trace_id_coverage, 4),
        "entity_coverage": round(1.0 - (missing_entity_type + missing_entity_name) / (2 * max(total, 1)), 4),
        "provenance_coverage": round(provenance_coverage, 4),
        "database_provenance_coverage": round(db_provenance_coverage, 4),
        "extraction_method_distribution": method_counts,
        # V2: per-entity extraction quality
        "per_entity_scores": per_entity_scores,
        "per_entity_issues": per_entity_issues,
        "issues": issues,
        "summary": "; ".join(issues) if issues else "提取质量良好。",
    }
