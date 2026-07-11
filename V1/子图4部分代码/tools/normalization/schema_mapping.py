"""schema_mapping.py — Tool 1: Schema Mapping"""
from typing import Any
from configs import load_yaml
from utils.logger import get_logger
logger = get_logger(__name__)

def map_to_target_schema(records: list[dict], field_mappings: dict[str, str],
                         target_schema: dict | None = None) -> dict[str, Any]:
    """将字段名映射到标准 Schema。"""
    config = load_yaml("schema_mapping.yaml")
    aliases: dict[str, str] = {}
    for f in config.get("target_schema", {}).get("fields", []):
        name = f.get("name", "")
        if name:
            aliases[name.lower()] = name
            for a in f.get("aliases", []):
                aliases[a.lower()] = name
    for k, v in (field_mappings or {}).items():
        aliases[k.lower()] = v

    log, unmapped = [], set()
    for rec in records:
        fn = rec.get("field_name", "")
        std = aliases.get(fn.lower())
        if std and std != fn:
            log.append({"record_id": rec.get("record_id"), "original": fn, "mapped": std})
            rec["field_name"] = std
        elif not std and fn:
            unmapped.add(fn)
    logger.info("[SchemaMapping] %d mapped, %d unmapped", len(log), len(unmapped))
    return {"data": records, "mapping_log": log, "unmapped": sorted(unmapped),
            "summary": f"Mapped {len(log)} fields" + (f", {len(unmapped)} unmapped" if unmapped else "")}
