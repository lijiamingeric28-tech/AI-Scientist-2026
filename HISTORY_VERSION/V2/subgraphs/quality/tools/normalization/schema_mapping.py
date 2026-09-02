"""schema_mapping.py — Tool 1: Schema Mapping"""
from typing import Any
from subgraphs.quality.configs import load_yaml
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

def map_to_target_schema(records: list[dict], field_mappings: dict[str, str],
                         target_schema: dict | None = None) -> dict[str, Any]:
    """将字段名映射到标准 Schema (V3.0: 自动领域切换)。"""
    # 优先从 context 传入的 target_schema, fallback 到配置
    if target_schema:
        schema_fields = target_schema.get("fields", [])
    else:
        from subgraphs.quality.configs import load_domain_schema_config
        schema_cfg = load_domain_schema_config("target_schema")
        schema_fields = schema_cfg.get("fields", [])
        # 最后 fallback: 通用配置
        if not schema_fields:
            config = load_yaml("schema_mapping.yaml")
            schema_fields = config.get("target_schema", {}).get("fields", [])
    aliases: dict[str, str] = {}
    for f in schema_fields:
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
