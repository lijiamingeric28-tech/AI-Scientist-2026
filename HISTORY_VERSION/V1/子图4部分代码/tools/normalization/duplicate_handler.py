"""duplicate_handler.py — Tool 5: Duplicate Handler"""
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

def handle_duplicates(records: list[dict]) -> dict[str, Any]:
    """精确 + 语义去重，并过滤 resolution_status=rejected 的记录。"""
    # 过滤 rejected
    orig = len(records)
    records = [r for r in records if r.get("_resolution_status") != "rejected"]
    rejected = orig - len(records)

    seen_ids, exact_dupes = set(), []
    deduped = []
    for rec in records:
        rid = rec.get("record_id", "")
        if rid and rid in seen_ids:
            exact_dupes.append(rid)
        else:
            seen_ids.add(rid)
            deduped.append(rec)

    seen_semantic, semantic_dupes = set(), []
    final = []
    for rec in deduped:
        # V1.1: entity 感知去重 — 不同实体的同值记录不应被去重
        key = (rec.get("source_id",""), rec.get("entity_type",""),
               rec.get("entity_name",""), rec.get("field_name",""),
               str(rec.get("field_value","")))
        if key in seen_semantic:
            semantic_dupes.append(rec.get("record_id","?"))
        else:
            seen_semantic.add(key)
            final.append(rec)

    total = len(exact_dupes) + len(semantic_dupes) + rejected
    logger.info("[Duplicate] %d removed (exact=%d, semantic=%d, rejected=%d)", total, len(exact_dupes), len(semantic_dupes), rejected)
    return {"data": final, "removed_count": total, "duplicate_ids": exact_dupes + semantic_dupes,
            "rejected_removed": rejected, "summary": f"Removed {total} duplicates/rejected"}
