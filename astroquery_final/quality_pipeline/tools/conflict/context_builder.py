"""
context_builder.py → V3.0: VarianceContextBuilder (原 ConflictContextBuilder)

V3.0 修改: 上下文从"冲突裁决辅助"改为"差异原因分析"。
  直接读取 V2 Record 字段 (measurement_method, condition_tags, extraction_confidence)
  而非从 title/abstract 正则推断。
"""
from __future__ import annotations
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)


def build_conflict_context(
    conflicts: list[dict],
    current_data: dict[str, Any],
    target_schema: dict[str, Any] | None,
) -> list[dict]:
    """
    V3.0: 为每个差异条目附加 V2 上下文 (直接读 Record 字段)。

    上下文内容:
      - 来源元数据 (title, year, journal, doi)
      - 每源 measurement_method (V2 Record 直接字段)
      - 每源 condition_tags (V2 Record 直接字段)
      - 每源 extraction_confidence (V2 Record 直接字段)
      - 时间因素 (year 差异)
      - 字段关键性 (来自 target_schema)

    Args:
        conflicts: 差异条目列表
        current_data: data_state.current_data (sources + records)
        target_schema: context_state.target_schema

    Returns:
        附加了上下文的差异条目列表
    """
    sources_list = current_data.get("sources", [])
    records_list = current_data.get("records", [])

    # source_id → source 元数据映射
    source_map: dict[str, dict] = {}
    for s in sources_list:
        source_map[s.get("source_id", "")] = s

    # source_id → records 映射
    source_records: dict[str, list[dict]] = {}
    for r in records_list:
        sid = r.get("source_id", "")
        source_records.setdefault(sid, []).append(r)

    # 字段关键性
    field_criticality: dict[str, str] = {}
    if target_schema:
        for f in target_schema.get("fields", []):
            field_criticality[f.get("name", "")] = f.get("criticality", "important")

    enriched = []
    for c in conflicts:
        # 支持新旧两种 source 标识方式
        source_ids: list[str] = c.get("source_ids", [])
        if not source_ids:
            sid_a = c.get("source_a", "")
            sid_b = c.get("source_b", "")
            source_ids = [s for s in (sid_a, sid_b) if s]

        fn = c.get("field_name", "")
        et = c.get("entity_type", "") or ""
        en = c.get("entity_name", "") or ""

        # ── V3.0: 直接读 V2 Record 字段 ──
        source_meta = {}
        source_detail = {}
        for sid in source_ids:
            src = source_map.get(sid, {})
            source_meta[sid] = {
                "title": src.get("title", ""),
                "year": src.get("year"),
                "journal": src.get("journal", ""),
                "doi": src.get("doi", ""),
            }

            # 收集此 source 在此 entity+field 下的 V2 字段
            methods: set[str] = set()
            tags: set[str] = set()
            confidences: list[float] = []
            for r in source_records.get(sid, []):
                r_et = r.get("entity_type", "") or ""
                r_en = r.get("entity_name", "") or ""
                r_fn = r.get("field_name", "")
                # entity-aware 过滤
                if et and en and r_et != et:
                    continue
                if en and r_en != en:
                    continue
                if fn and r_fn != fn:
                    continue
                mm = r.get("measurement_method", "")
                if mm:
                    methods.add(mm)
                ct = r.get("condition_tags", [])
                if isinstance(ct, list):
                    tags.update(ct)
                ec = r.get("extraction_confidence")
                if ec is not None:
                    confidences.append(float(ec))
            source_detail[sid] = {
                "measurement_methods": sorted(methods),
                "condition_tags": sorted(tags),
                "avg_extraction_confidence": (
                    round(sum(confidences) / len(confidences), 3)
                    if confidences else None
                ),
            }

        # ── V3.0: 差异原因推断所需信息 ──
        methods_by_source = {
            sid: set(d["measurement_methods"]) for sid, d in source_detail.items()
        }
        tags_by_source = {
            sid: set(d["condition_tags"]) for sid, d in source_detail.items()
        }
        all_methods = set().union(*methods_by_source.values())
        all_tags = set().union(*tags_by_source.values())
        methods_differ = (
            len(all_methods) > 0
            and any(
                methods_by_source.get(sia) != methods_by_source.get(sib)
                for i, sia in enumerate(source_ids)
                for sib in source_ids[i + 1:]
            )
        )
        tags_differ = (
            len(all_tags) > 0
            and any(
                tags_by_source.get(sia) != tags_by_source.get(sib)
                for i, sia in enumerate(source_ids)
                for sib in source_ids[i + 1:]
            )
        )

        # 时间因素
        years = [source_meta[sid].get("year") for sid in source_ids if source_meta[sid].get("year")]
        temporal_gap = max(years) - min(years) if len(years) >= 2 else None

        # 值范围
        values = [
            c.get("mean_a"), c.get("mean_b"),
            *[ss.get("mean") for ss in (c.get("source_stats") or {}).values()]
        ]
        values = [v for v in values if v is not None]
        value_range = [min(values), max(values)] if len(values) >= 2 else None

        enriched.append({
            **c,
            "context": {
                "source_meta": source_meta,
                "source_detail": source_detail,
                "all_measurement_methods": sorted(all_methods),
                "all_condition_tags": sorted(all_tags),
                "methods_differ": methods_differ,
                "tags_differ": tags_differ,
                "temporal_gap_years": temporal_gap,
                "value_range": value_range,
                "field_criticality": field_criticality.get(fn, "important"),
            },
        })

    logger.info("[VarianceContextBuilder V3.0] Built context for %d items", len(enriched))
    return enriched
