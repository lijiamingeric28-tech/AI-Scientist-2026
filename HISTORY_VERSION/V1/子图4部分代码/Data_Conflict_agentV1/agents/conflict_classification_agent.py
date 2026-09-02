"""
conflict_classification_agent.py → V3.0: DifferenceClassificationAgent (Stage 2)

职责: 对每组多源差异分类原因 (methodological/condition/temporal/uncertainty/duplicate)。
      规则分类器处理确定项, LLM 补充不确定项 (利用 context_snippet)。
LLM: 是 (仅 undetermined 案例) | Tools: 0 (直接读 variance context)
"""
from __future__ import annotations
import datetime, json, re, time
from typing import Any
from quality_state import QualityGraphState
from utils.llm import get_llm, set_agent_context, track_raw_llm_call
from utils.logger import get_logger
logger = get_logger(__name__)

# V3.0: 差异原因分类体系
_CAUSE_LABELS = {
    "methodological_variance": "不同观测方法/仪器导致的系统性差异",
    "condition_variance": "不同观测条件/波段导致的差异",
    "temporal_variation": "不同时间观测导致的变化",
    "measurement_uncertainty": "测量误差范围内的正常波动",
    "duplicate_observation": "同一测量在不同来源中重复出现",
    "unknown": "无法确定差异原因",
}

_CLASSIFICATION_SYSTEM = """You are an astronomical data variance classification expert.

Classify the CAUSE of differences between multiple measurements of the same astronomical entity+field.
Use the provided context_snippets (text excerpts from the original papers) to determine the measurement method,
instrument, observation band, and epoch when the metadata fields are insufficient.

Causes:
- methodological_variance: different measurement methods/instruments (e.g., spectroscopy vs photometry, FAST vs VLA)
- condition_variance: different observation conditions/bands (e.g., L-band vs C-band, optical vs X-ray)
- temporal_variation: observations at different epochs (time gap > 5 years) — this is scientifically valuable, NOT a conflict
- measurement_uncertainty: differences within normal measurement error range
- duplicate_observation: the exact same measurement reported in multiple papers
- unknown: cannot determine the cause

Output JSON: {"classifications": [{"entity_type":..., "entity_name":..., "field_name":..., "cause":..., "confidence":..., "reason":...}]}"""


class DifferenceClassificationAgent:
    """V3.0 Stage 2: 差异原因分类 — 规则 + LLM 补充"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        aggregation = conflict_state.get("aggregation", {})
        variances = aggregation.get("variances", [])
        anomalies = aggregation.get("anomalies", [])

        quality = state.get("report_state", {}).get("quality", {}) or {}
        msv = quality.get("multi_source_variance", {})
        raw_variances = msv.get("variances", [])

        llm_count = wf.get("llm_call_count", 0)

        classified_variances = []
        needs_llm = []

        # ── 构建原始方差字典 (按 key) ──
        raw_by_key = {}
        for rv in raw_variances:
            key = (rv.get("entity_type", ""), rv.get("entity_name", ""), rv.get("field_name", ""))
            raw_by_key[key] = rv

        for v in variances:
            et = v.get("entity_type", "")
            en = v.get("entity_name", "")
            fn = v.get("field_name", "")
            key = (et, en, fn)
            raw = raw_by_key.get(key, {})

            # ── 规则分类 ──
            inferred = v.get("inferred_cause", "unknown")
            cause_conf = v.get("cause_confidence", 0)

            # 规则分类置信度阈值: >=0.65 → 确定, 否则 → LLM
            if inferred != "unknown" and cause_conf >= 0.65:
                classified_variances.append({
                    **v,
                    "classified_cause": inferred,
                    "cause_confidence_final": cause_conf,
                    "classification_method": "rule",
                    "classification_reason": _CAUSE_LABELS.get(inferred, inferred),
                })
            else:
                needs_llm.append(v)

        # ── LLM 补充不确定项 (V3.0: 包含 context_snippet) ──
        if needs_llm:
            try:
                set_agent_context("difference_classification")
                llm = get_llm(temperature=0.0)

                # 从 data_state 读取 records 以获取 context_snippet
                data = state.get("data_state", {}).get("current_data", {})
                all_records = data.get("records", [])
                # 构建 (entity_type, entity_name, field_name, source_id) → context_snippets 映射
                snippet_map: dict[tuple, list[str]] = {}
                for r in all_records:
                    key = (
                        r.get("entity_type", "") or "",
                        r.get("entity_name", "") or "",
                        r.get("field_name", ""),
                        r.get("source_id", ""),
                    )
                    cs = r.get("context_snippet", "")
                    if cs:
                        snippet_map.setdefault(key, []).append(cs[:300])  # 截断到300字符

                llm_input = []
                for v in needs_llm:
                    sd = v.get("source_details", {})
                    methods = set()
                    tags = set()
                    years = set()
                    snippets: list[str] = []
                    et = v.get("entity_type", "") or ""
                    en = v.get("entity_name", "") or ""
                    fn = v.get("field_name", "")
                    for sid, detail in sd.items():
                        methods.update(detail.get("measurement_methods", []))
                        tags.update(detail.get("condition_tags", []))
                        y = detail.get("year")
                        if y:
                            years.add(y)
                        # V3.0: 读取 context_snippet
                        snip_key = (et, en, fn, sid)
                        snips = snippet_map.get(snip_key, [])
                        if not snips:
                            # fallback: 不区分 entity
                            for k, v_snips in snippet_map.items():
                                if k[2] == fn and k[3] == sid:
                                    snips = v_snips
                                    break
                        snippets.extend(snips)
                    llm_input.append({
                        "entity_type": et,
                        "entity_name": en,
                        "field_name": fn,
                        "value_range": v.get("value_range", []),
                        "methods_used": sorted(methods),
                        "condition_tags": sorted(tags),
                        "years": sorted(years) if years else None,
                        "max_cohens_d": v.get("max_cohens_d", 0),
                        "context_snippets": snippets[:2],  # 最多2条, 每条300字符
                    })

                prompt = (
                    f"Classify the cause of measurement differences for these "
                    f"{len(llm_input)} entities:\n{json.dumps(llm_input, indent=2)}"
                )
                resp = llm.invoke([
                    {"role": "system", "content": _CLASSIFICATION_SYSTEM},
                    {"role": "user", "content": prompt},
                ])
                llm_text = resp.content if hasattr(resp, "content") else str(resp)
                json_match = re.search(r'\{.*\}', llm_text, re.DOTALL)
                llm_classifications = []
                if json_match:
                    llm_result = json.loads(json_match.group(0))
                    llm_classifications = llm_result.get("classifications", [])

                llm_count += 1
                track_raw_llm_call(time.time() - t0, agent="difference_classification")

                # 合并 LLM 结果
                llm_map = {
                    (c.get("entity_type", ""), c.get("entity_name", ""), c.get("field_name", "")): c
                    for c in llm_classifications
                }
                for v in needs_llm:
                    key = (v.get("entity_type", ""), v.get("entity_name", ""), v.get("field_name", ""))
                    if key in llm_map:
                        lc = llm_map[key]
                        v["classified_cause"] = lc.get("cause", "unknown")
                        v["cause_confidence_final"] = lc.get("confidence", 0.5)
                        v["classification_method"] = "llm"
                        v["classification_reason"] = lc.get("reason", "")
                    else:
                        v["classified_cause"] = "unknown"
                        v["cause_confidence_final"] = 0.3
                        v["classification_method"] = "fallback"
                        v["classification_reason"] = "LLM could not determine cause"
                    classified_variances.append(v)

            except Exception as e:
                logger.warning("[DifferenceClassification] LLM failed: %s", e)
                for v in needs_llm:
                    v["classified_cause"] = "unknown"
                    v["cause_confidence_final"] = 0.2
                    v["classification_method"] = "fallback"
                    v["classification_reason"] = f"LLM error: {e}"
                    classified_variances.append(v)

        # ── 分组统计 ──
        by_cause: dict[str, list] = {}
        by_entity: dict[str, dict] = {}
        for v in classified_variances:
            cause = v.get("classified_cause", "unknown")
            by_cause.setdefault(cause, []).append(v.get("field_name", ""))
            et = v.get("entity_type", "") or ""
            en = v.get("entity_name", "") or "unknown"
            elabel = f"{et}:{en}" if et else en
            if elabel not in by_entity:
                by_entity[elabel] = {"total": 0, "by_cause": {}}
            by_entity[elabel]["total"] += 1
            by_entity[elabel]["by_cause"][cause] = by_entity[elabel]["by_cause"].get(cause, 0) + 1

        # 异常保持原样传入下一 stage
        elapsed = round(time.time() - t0, 3)
        logger.info("[DifferenceClassification] %d variances: %s",
                    len(classified_variances),
                    ", ".join(f"{k}={len(v)}" for k, v in by_cause.items()))

        return {
            "report_state": {"conflict": {
                "classification": {
                    "classified_variances": classified_variances,
                    "anomalies": anomalies,
                    "by_cause": by_cause,
                    "by_entity": by_entity,
                }
            }},
            "workflow_state": {
                "current_node": "difference_classification",
                "execution_status": "Success",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "DifferenceClassificationAgent", "stage": "Classification",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Classified {len(classified_variances)} variances ({len(needs_llm)} via LLM)",
                }],
            },
        }
