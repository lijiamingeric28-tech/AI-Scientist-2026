"""
context_builder.py — 从 state 构建 LLM 洞察输入上下文 (V3.4)

按 source_type 分支 (V3.4 database 感知):
  - paper records:   context_snippet / measurement_method / condition_tags / extraction_confidence
  - paper sources:   abstract
  - database sources: description / research_content / research_methodology / waveband / reference_paper
"""
from __future__ import annotations

from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)


def _safe(val, default=""):
    return val if val is not None else default


def build_field_summaries(state: dict[str, Any]) -> list[dict]:
    """按 (entity_type, entity_name, field_name, source_type) 聚合字段摘要。

    Returns:
        [{
            entity_type, entity_name, field_name, source_type,
            source_ids, record_count,
            value_range, values_sample,
            units, methods, conditions,
            extraction_confidences, context_snippets,
        }]
    """
    data = state.get("data_state", {}).get("current_data", {}) or {}
    records = data.get("records", []) or []
    sources = {s.get("source_id", ""): s for s in (data.get("sources", []) or [])}
    # V4 fix: 实体类型规范化 — "Unknown"/空 → 按目录/字段/语义类型推断 (Simbad otypes)
    domain = (state.get("context_state") or {}).get("research_domain", "astrophysics")
    from ...tools.insight.entity_types import normalize_entity_type

    groups: dict[tuple, dict] = {}
    # V3.4 fix: database_catalog_properties → 语义聚合细分 (raw_column 前缀归类)
    for r in records:
        sid = r.get("source_id", "")
        src = sources.get(sid, {})
        # V4 fix: 实体类型规范化 — "Unknown"/空 → 按目录/字段/语义类型推断
        et = normalize_entity_type(r.get("entity_type", "") or "",
                                   r.get("field_name", ""), src, domain)
        en = r.get("entity_name", "") or ""
        fn = r.get("field_name", "")
        stype = src.get("source_type", "paper")

        # V3.4 fix: catch-all 字段按 raw_column 语义聚合 (Fnu_*→flux_density, recno→catalog_identifier...)
        if fn == "database_catalog_properties" and stype == "database":
            rc = (r.get("provenance") or {}).get("raw_column", "")
            if rc:
                fn = _semantic_group(rc)  # 语义聚合 → 物理量级粒度
            else:
                fn = "catalog_identifier"

        key = (et, en, fn, stype)
        g = groups.setdefault(key, {
            "entity_type": et, "entity_name": en, "field_name": fn,
            "source_type": stype, "source_ids": set(),
            "values": [], "units": set(),
            "methods": set(), "conditions": set(),
            "confidences": [], "snippets": [],
            "source_meta": set(),
        })
        g["source_ids"].add(sid)
        g["values"].append(r.get("field_value"))
        if r.get("field_unit"):
            g["units"].add(r["field_unit"])
        if stype == "paper":
            if r.get("measurement_method"):
                g["methods"].add(r["measurement_method"])
            for t in (r.get("condition_tags") or []):
                if t:
                    g["conditions"].add(t)
            if r.get("extraction_confidence") is not None:
                g["confidences"].append(float(r["extraction_confidence"]))
            if r.get("context_snippet"):
                g["snippets"].append(str(r["context_snippet"])[:200])
        else:
            # database: source 层上下文
            if src.get("research_methodology"):
                g["methods"].add(str(src["research_methodology"])[:150])
            if src.get("waveband"):
                g["conditions"].add(str(src["waveband"]))
            if src.get("research_content"):
                g["snippets"].append(str(src["research_content"])[:200])
            g["confidences"].append(1.0)  # V3.4: 结构化查询视为高置信

    result = []
    for g in groups.values():
        vals = g["values"]
        numeric = [v for v in vals if isinstance(v, (int, float))]
        try:
            numeric = [float(v) for v in vals if _is_numeric(v)]
        except (TypeError, ValueError):
            pass
        value_range = None
        if len(numeric) >= 2:
            value_range = [min(numeric), max(numeric)]
        elif len(numeric) == 1:
            value_range = [numeric[0], numeric[0]]

        result.append({
            "entity_type": g["entity_type"],
            "entity_name": g["entity_name"],
            "field_name": g["field_name"],
            "source_type": g["source_type"],
            "source_ids": sorted(g["source_ids"]),
            "record_count": len(vals),
            "value_range": value_range,
            "values_sample": [str(v)[:60] for v in vals[:5]],
            "units": sorted(g["units"]),
            "methods": sorted(g["methods"]),
            "conditions": sorted(g["conditions"]),
            "avg_extraction_confidence": (
                round(sum(g["confidences"]) / len(g["confidences"]), 3)
                if g["confidences"] else None
            ),
            "context_snippets": g["snippets"][:3],
        })
    return result


# 纯标识符列 (无物理量意义)
_IDENTIFIER_COLS = {
    "recno", "simbad", "ned", "leda", "mcg", "tycho", "link", "anames",
    "o_anames", "idtype", "xid", "dupsrc", "extkey", "pxkey", "all",
    "rem", "disc", "possposs", "confuse",
    # V3.4: 杂项标志/辅助列 (单条, 归入标识符组)
    "mhcon", "nhcon", "pnearh", "pnearw", "prox", "usesrc", "idgal",
    "poss", "i", "sb/a", "cc", "int", "hsdflag", "supdedeg", "supradeg",
    "pxpa", "var",
}


def _semantic_group(raw_col: str) -> str:
    """DB 原始列名 → 语义聚合组 (V3.4: 粒度细化到物理量级)。

    EAV 模型下每条记录是一个物理量 (如 Fnu_12), catch-all 将其聚合为单字段。
    按列名前缀归类:
      Fnu_*       → flux_density        (IRAS 波段通量密度)
      CC_*        → color_index         (IRAS 色指数)
      SES*/e_*    → measurement_error   (通量误差)
      q_*         → quality_flag        (探测质量标志)
      Cirr*       → cirrus_flag         (IRAS 卷云污染)
      H./J./K.*   → 2mass_photometry    (2MASS 各波段测光)
      logD/logR   → galaxy_size         (星系直径/半径)
      MajAxis等   → galaxy_morphology   (星系形态参数)
      Hubble/MType→ morphological_type  (形态类型)
      其他标识符  → catalog_identifier
    """
    col = (raw_col or "").lower()
    if col in _IDENTIFIER_COLS:
        return "catalog_identifier"
    if col.startswith(("fnu_", "fcor_")):
        return "flux_density"   # IRAS 波段通量密度 (含修正通量)
    if col.startswith("tsnr_"):
        return "signal_to_noise"  # 波段信噪比
    if col == "pmag":
        return "apparent_magnitude"  # POSS 照片星等
    if col.startswith("cc_"):
        return "color_index"
    if col.startswith(("ses", "e_fnu", "e_pa", "e_log", "e_h", "e_j", "e_k", "f_h", "f_j", "f_k")):
        return "measurement_error"
    if col.startswith("q_"):
        return "quality_flag"
    if col.startswith("cirr"):
        return "cirrus_flag"
    # 2MASS 波段列: H/J/K 前缀 + 第二字符为波段属性 (b/a轴比 c集中度 m表面亮度 p位置角 r半径 .或_)
    if col.startswith(("h.", "j.", "k.", "r.")) or (
        len(col) > 1 and col[0] in "hjk" and col[1] in ".bcmpr_"
    ):
        return "2mass_photometry"
    if col.startswith(("logd", "logr")):
        return "galaxy_size"
    if col in ("majaxis", "minaxis", "pa", "posang", "spa", "ar", "br", "aR", "bR"):
        return "galaxy_morphology"
    if col in ("hubble", "mtype", "otype", "nid", "nlrs", "vnls", "hconcent", "jconc", "kconc"):
        return "morphological_type"
    if col.startswith(("ra", "de", "_ra", "_de")) or col in ("_RA.icrs", "_DE.icrs"):
        return "sky_position"
    # V3.4 fix: 精确匹配 proper_motion (排除 "pmag" 照片星等)
    if col == "pm" or col.startswith(("pmra", "pmdec", "pm_")):
        return "proper_motion"
    return col  # 未归类 → 保留原始列名


def _is_numeric(v) -> bool:
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.strip())
            return True
        except (ValueError, TypeError):
            return False
    return False


def build_source_summaries(state: dict[str, Any]) -> list[dict]:
    """来源摘要 — paper 用 abstract, database 用 description/research_content。"""
    data = state.get("data_state", {}).get("current_data", {}) or {}
    result = []
    for s in (data.get("sources", []) or []):
        stype = s.get("source_type", "paper")
        if stype == "database":
            result.append({
                "source_id": s.get("source_id", ""),
                "source_type": "database",
                "title": s.get("title", ""),
                "description": _safe(s.get("description"))[:300],
                "research_content": _safe(s.get("research_content"))[:300],
                "research_methodology": _safe(s.get("research_methodology"))[:300],
                "waveband": _safe(s.get("waveband")),
                "reference_paper": _safe(s.get("reference_paper"))[:150],
                "vizier_table_id": _safe(s.get("vizier_table_id")),
            })
        else:
            result.append({
                "source_id": s.get("source_id", ""),
                "source_type": "paper",
                "title": s.get("title", ""),
                "abstract": _safe(s.get("abstract"))[:300],
                "keywords": s.get("keywords", []) or [],
                "journal": _safe(s.get("journal")),
                "year": s.get("year"),
            })
    return result


def build_quality_context(state: dict[str, Any]) -> dict:
    """质量相关上下文: 评分 + 冲突 + 处理统计。"""
    rs = state.get("report_state", {}) or {}
    quality = rs.get("quality") or {}
    wf = state.get("workflow_state", {}) or {}

    scoring = quality.get("quality_scoring", {}) or {}
    conflict = rs.get("conflict") or {}
    resolution = conflict.get("resolution_report") or {}
    norm = rs.get("normalization") or {}
    mods = norm.get("modifications", {}) or {}

    return {
        "overall_score": scoring.get("overall_score"),
        "quality_level": scoring.get("quality_level"),
        "calibrated_confidence": scoring.get("calibrated_confidence"),
        "route_counts": quality.get("route_counts", {}),
        "anomalies": (quality.get("multi_source_variance") or {}).get("anomaly_count", 0),
        "variance_groups": (quality.get("multi_source_variance") or {}).get("variance_count", 0),
        "conflict_status": resolution.get("status"),
        "conflict_route": resolution.get("route_decision"),
        "normalization_mods": mods.get("total", 0),
        "llm_calls": wf.get("llm_call_count", 0),
        "tool_calls": wf.get("tool_call_count", 0),
        "loop_round": wf.get("loop_round", 0),
    }


def build_low_confidence_records(state: dict[str, Any]) -> list[dict]:
    """确定性: paper records extraction_confidence 低于阈值 (DB records 无该字段, 跳过)。"""
    from ...configs.domain_config import LOW_CONFIDENCE_THRESHOLD  # V3.5: 配置单一入口
    data = state.get("data_state", {}).get("current_data", {}) or {}
    sources = {s.get("source_id", ""): s for s in (data.get("sources", []) or [])}
    low = []
    for r in (data.get("records", []) or []):
        stype = (sources.get(r.get("source_id", "")) or {}).get("source_type", "paper")
        if stype == "database":
            continue  # V3.4: DB 结构化提取视为高置信
        conf = r.get("extraction_confidence")
        if conf is not None and float(conf) < LOW_CONFIDENCE_THRESHOLD:
            low.append({
                "record_id": r.get("record_id", ""),
                "field_name": r.get("field_name", ""),
                "entity_name": r.get("entity_name", ""),
                "extraction_confidence": float(conf),
            })
    return low


def build_coverage_gaps(state: dict[str, Any]) -> list[str]:
    """确定性: per_entity_missing 聚合 (来自 Assessment completeness)。"""
    rs = state.get("report_state", {}) or {}
    quality = rs.get("quality") or {}
    gaps = []
    for sid, sr in (quality.get("sources") or {}).items():
        missing = (sr.get("completeness") or {}).get("missing_expected_fields", [])
        if missing:
            gaps.append(f"{sid}: missing {sorted(missing)[:5]}")
    return gaps
