"""duplicate_handler.py — Tool 5: Duplicate Handler"""
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)

def _canonical_unit(unit: str) -> str:
    """M-21 fix: 单位归一化 (小写 + 去空白), 供语义去重 key 使用。"""
    return unit.strip().lower().replace(" ", "")


def handle_duplicates(records: list[dict]) -> dict[str, Any]:
    """精确 + 语义去重，并过滤 resolution_status=rejected 的记录。"""
    # 过滤 rejected (M-15 fix: 同时记录被拒记录 id, 供逐条 trace)
    rejected_ids = []
    kept = []
    for rec in records:
        if rec.get("_resolution_status") == "rejected":
            rejected_ids.append(rec.get("record_id", "?"))
        else:
            kept.append(rec)
    records = kept
    rejected = len(rejected_ids)

    seen_ids, exact_dupes = set(), []
    deduped = []
    for rec in records:
        rid = rec.get("record_id", "")
        if rid and rid in seen_ids:
            exact_dupes.append(rid)
        else:
            seen_ids.add(rid)
            deduped.append(rec)

    # M-21 fix: 语义去重 key 纳入 canonical 归一化后的 field_unit —
    # 同值不同单位 (如 5 pc vs 5 kpc) 不再被静默判重复删除
    seen_value: dict = {}   # 值 key → 首条 record_id (用于检测同值不同单位)
    seen_full: set = set()  # 值 key + 单位 key
    semantic_dupes, semantic_warnings = [], []
    final = []
    for rec in deduped:
        # V1.1: entity 感知去重 — 不同实体的同值记录不应被去重
        value_key = (rec.get("source_id",""), rec.get("entity_type",""),
                     rec.get("entity_name",""), rec.get("field_name",""),
                     str(rec.get("field_value","")))
        unit_key = _canonical_unit(str(rec.get("field_unit", "") or ""))
        full_key = (value_key, unit_key)
        if full_key in seen_full:
            semantic_dupes.append(rec.get("record_id","?"))
        elif value_key in seen_value:
            # 同值不同单位 — 跳过删除并记 warning (两条都保留)
            semantic_warnings.append({
                "record_id": rec.get("record_id", "?"),
                "other_record_id": seen_value[value_key],
                "field": rec.get("field_name", ""),
                "unit": rec.get("field_unit", "") or "",
                "action": "unit_mismatch_kept",
            })
            logger.warning("[Duplicate] %s: same value different unit, kept both",
                           rec.get("record_id", "?"))
            seen_full.add(full_key)
            final.append(rec)
        else:
            seen_value[value_key] = rec.get("record_id", "?")
            seen_full.add(full_key)
            final.append(rec)

    total = len(exact_dupes) + len(semantic_dupes) + rejected
    logger.info("[Duplicate] %d removed (exact=%d, semantic=%d, rejected=%d)", total, len(exact_dupes), len(semantic_dupes), rejected)
    return {"data": final, "removed_count": total, "duplicate_ids": exact_dupes + semantic_dupes,
            "rejected_ids": rejected_ids, "rejected_removed": rejected,
            "semantic_warnings": semantic_warnings,
            "summary": f"Removed {total} duplicates/rejected"}
