"""
conflict_extractor.py → V3.0: VarianceExtractor (原 ConflictExtractor)

V3.0 重写: 从 Quality Report 提取多源方差和异常, 替代旧的冲突提取。
  - A→C: 读 quality.multi_source_variance (variances + anomalies)
  - B→C: 读 normalization.validation 中的方差分析结果

去重: 按 (entity_type, entity_name, field_name, source_ids) 去重, 不再按 Cohen's d 选最高。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def extract_conflicts(
    quality_report: dict[str, Any] | None,
    normalization_report: dict[str, Any] | None,
    trigger_path: str,
) -> dict[str, Any]:
    """
    V3.0: 提取多源方差和异常 (兼容旧 API 名称)。

    Args:
        quality_report: Assessment 的 quality report (V3.0: 含 multi_source_variance)
        normalization_report: Normalization 的 report (B→C 路径)
        trigger_path: "A→C" 或 "B→C"

    Returns:
        {trigger_path, total_variances, total_anomalies, variances, anomalies,
         involved_sources, involved_fields, involved_entities, summary}
    """
    raw_variances: list[dict] = []
    raw_anomalies: list[dict] = []

    if trigger_path == "A→C" and quality_report:
        # ── V3.0: 从 multi_source_variance 读取 ──
        msv = quality_report.get("multi_source_variance", {})
        if msv:
            for v in msv.get("variances", []):
                v["_source_path"] = "A→C"
                raw_variances.append(v)
            for a in msv.get("anomalies", []):
                a["_source_path"] = "A→C"
                raw_anomalies.append(a)

        # ── 向后兼容: 如果 multi_source_variance 为空, fallback 到 conflict_risk ──
        if not raw_variances and not raw_anomalies:
            sources = quality_report.get("sources", {})
            for sid, src in sources.items():
                cr = src.get("conflict_risk", {})
                for c in cr.get("conflicts", []):
                    c["_source_path"] = "A→C"
                    raw_anomalies.append(c)

    elif trigger_path == "B→C" and normalization_report:
        validation = normalization_report.get("validation", {})
        variance_check = validation.get("variance_check", validation.get("conflict_check", {}))
        for v in variance_check.get("variances", []):
            v["_source_path"] = "B→C"
            raw_variances.append(v)
        for a in variance_check.get("anomalies", variance_check.get("conflicts", [])):
            a["_source_path"] = "B→C"
            raw_anomalies.append(a)

    # ── 去重: V3.0 不再按 Cohen's d 选最高, 而是按 source_id 集合去重 ──
    _dedupe_variances(raw_variances)
    _dedupe_anomalies(raw_anomalies)

    # ── 汇总 ──
    involved_sources: set[str] = set()
    involved_fields: set[str] = set()
    involved_entities: set[str] = set()

    for v in raw_variances:
        involved_sources.update(v.get("source_ids", []))
        involved_fields.add(v.get("field_name", ""))
        et = v.get("entity_type", "") or ""
        en = v.get("entity_name", "") or ""
        if et or en:
            involved_entities.add(f"{et}:{en}" if et else en)

    for a in raw_anomalies:
        sid = a.get("source_id", "")
        if sid:
            involved_sources.add(sid)
        sa, sb = a.get("source_a", ""), a.get("source_b", "")
        if sa:
            involved_sources.add(sa)
        if sb:
            involved_sources.add(sb)
        involved_fields.add(a.get("field_name", ""))
        et = a.get("entity_type", "") or ""
        en = a.get("entity_name", "") or ""
        if et or en:
            involved_entities.add(f"{et}:{en}" if et else en)

    total_v = len(raw_variances)
    total_a = len(raw_anomalies)

    summary = (
        f"Extracted {total_v} variance group(s) and {total_a} anomal(ies) "
        f"via {trigger_path} across {len(involved_sources)} source(s)"
    )

    logger.info("[VarianceExtractor V3.0] %d variances, %d anomalies (%s), sources=%d",
                total_v, total_a, trigger_path, len(involved_sources))

    return {
        "trigger_path": trigger_path,
        "total_conflicts": total_a,               # 向后兼容
        "total_variances": total_v,
        "total_anomalies": total_a,
        "conflicts": raw_anomalies,               # 向后兼容 (旧代码读 conflicts)
        "variances": raw_variances,
        "anomalies": raw_anomalies,
        "involved_sources": sorted(involved_sources),
        "involved_entities": sorted(involved_entities),
        "involved_fields": sorted(involved_fields),
        "summary": summary,
    }


def _dedupe_variances(variances: list[dict]) -> None:
    """V3.0: 方差去重 — 按 (entity, field, source_ids) 去重, 保留第一个。"""
    seen: dict[tuple, int] = {}
    for i, v in enumerate(variances):
        key = (
            v.get("entity_type", ""),
            v.get("entity_name", ""),
            v.get("field_name", ""),
            tuple(sorted(v.get("source_ids", []))),
        )
        if key in seen:
            variances[i] = None  # mark for removal
        else:
            seen[key] = i
    # 原地删除
    variances[:] = [v for v in variances if v is not None]


def _dedupe_anomalies(anomalies: list[dict]) -> None:
    """V3.0: 异常去重 — 按 (anomaly_type, entity_name, field_name) 去重。"""
    seen: set[tuple] = set()
    for i, a in enumerate(anomalies):
        key = (
            a.get("anomaly_type", ""),
            a.get("entity_name", ""),
            a.get("field_name", ""),
        )
        if key in seen:
            anomalies[i] = None
        else:
            seen.add(key)
    anomalies[:] = [a for a in anomalies if a is not None]
