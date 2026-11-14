"""Issue-driven usability assessment. Scores never decide processing routes."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from astroquery_ai.runtime.codec import digest


def check_native_dimension(repository, conn, task_id, record, binding):
    """Reject a proven wrong linear measurand, never infer a conversion.

    Compatibility alone does NOT establish physical identity. Missing/encoded
    units remain subject to the existing semantic checks. This gate uses the
    actual numeric source column, not the model's guessed unit or its score.
    """
    if (record.get('source_kind') not in {'catalog', 'official_attachment'}
            or record['value']['kind'] not in {'real', 'integer'} or record['representation'] != 'linear'
            or binding['output_profile']['representation']['kind'] != 'linear'
            or binding['output_profile']['unit']['kind'] != 'physical'):
        return True
    from astroquery_ai.runtime.codec import content_hash
    from astroquery_ai.runtime.errors import DomainError
    refs = [(record['source_ref'], 'source'), (record['interpretation_ref'], 'interpretation')]
    originals = []
    for reference, kind in refs:
        original = repository.object(conn, task_id, kind, reference['id'], reference['version'])
        if content_hash(original) != reference['content_sha256']:
            raise DomainError('SNAPSHOT_REFERENCE_MISMATCH', '原始来源或解释引用不一致')
        originals.append(original)
    source, interpretation = originals
    if source.get('kind') not in {'catalog', 'official_attachment'}:
        return True
    column = interpretation.get('proposal', {}).get('column')
    fields = [c for c in source.get('metadata', {}).get('columns', []) if c['name'] == column]
    if len(fields) != 1 or not fields[0].get('unit_text') or fields[0].get('datatype') not in {
        'unsignedByte', 'short', 'int', 'long', 'float', 'double',
    }:
        return True
    from .units import parse_unit
    from .unit_declarations import output_coordinate_unit
    try:
        native = parse_unit(fields[0]['unit_text'])
        target_text = output_coordinate_unit(binding['output_profile'])
        target = parse_unit(target_text)
        from astropy import units
        if (hasattr(native, 'physical_unit') or native in (units.mag, units.dex, units.dB)
                or str(native.physical_type) in {'unknown', 'dimensionless'}
                or str(target.physical_type) in {'unknown', 'dimensionless'}
                or native.is_equivalent(target, equivalencies=units.temperature())):
            return True
    except (ValueError, TypeError):
        return True  # No dimension claim is made about an unresolved encoding.
    reference = {'id': record['measurement_id'], 'version': record['revision'],
                 'content_sha256': record['content_sha256']}
    disposition = {'schema_version': 'NativeQuantityDimensionCheck/1', 'owner': 'M07',
        'measurement_id': record['measurement_id'], 'measurement_ref': reference, 'status': 'not_supported',
        'reason': 'native_linear_dimension_conflicts_with_selected_quantity',
        'source_ref': record['source_ref'], 'source_column': column,
        'source_unit': fields[0]['unit_text'], 'target_unit': target_text,
        'source_dimension': str(native.physical_type), 'target_dimension': str(target.physical_type),
        'evidence_refs': record['evidence_refs'], 'raw_value_and_uncertainty_retained': True,
        'scientific_derivation_performed': False}
    repository.put_object(conn, task_id, 'admission_disposition', 'native-dimension-' + digest(disposition), 1, disposition)
    return False


def assess(
    measurements: list[dict],
    derived: list[dict],
    selected_property_ids: list[str],
    *,
    snapshot_ref: dict,
    source_groups: dict[str, str],
    source_cautions: dict[str, list[dict]],
    source_checks: dict | None = None,
    phase="final",
) -> dict:
    normalized = {d["measurement_id"]: d for d in derived}
    records, issues, processing = [], [], []
    groups = defaultdict(list)
    for measurement in sorted(measurements, key=lambda m: m["measurement_id"]):
        mid, pid, source = (
            measurement["measurement_id"],
            measurement["property_ref"]["id"],
            measurement["source_ref"]["id"],
        )
        output = normalized.get(mid)
        retained = {c["source_component_id"]: c for c in (output or {}).get("uncertainty_typed", {}).get("components", [])
                    if c.get("semantic_state") == "unresolved"} if (output or {}).get("uncertainty_typed") else {}
        for component in measurement["uncertainty"]["components"]:
            if component["interpretation_state"] == "unresolved" or component["component_id"] in retained:
                issues.append(
                    {
                        "issue_key": digest(
                            {
                                "rule": "reported_uncertainty_unresolved",
                                "measurement": mid,
                                "component": component["component_id"],
                            }
                        ),
                        "rule_id": "reported_uncertainty_unresolved",
                        "category": "usage_limit",
                        "measurement_ids": [mid],
                        "property_id": pid,
                        "component_ids": [component["component_id"]],
                        "state": "retained_unresolved",
                        "message": "主值保留；该原报误差的形式或含义仍未确定。",
                        "evidence_refs": component["evidence_refs"],
                        "impact": {
                            "dimension": "none",
                            "level": None,
                            "reason": "optional_source_uncertainty_unresolved",
                        },
                    }
                )
        delivery = None
        if output:
            if output["status"] == "ready" and output["main_state"] == "ready":
                delivery = 100
            elif output["main_state"] == "ready" and output["status"] == "partial":
                delivery = 50
            elif output["main_state"] == "failed":
                delivery = 0
        if delivery != 100:
            code = (
                "target_representation_missing"
                if output is None
                else "target_representation_" + output["status"]
            )
            issue = {
                "issue_key": digest({"rule": code, "measurement": mid}),
                "rule_id": code,
                "category": "usage_limit" if output and output.get('source_only_limitation') else "delivery_defect" if delivery is not None else "check_failure",
                "measurement_ids": [mid],
                "property_id": pid,
                "state": "open",
                "message": code,
                "impact": {"dimension": "none" if output and output.get('source_only_limitation') else "delivery", "level": delivery, "reason": code},
            }
            issues.append(issue)
            if output is None and phase != "final":
                processing.append(
                    {
                        "item_id": "normalize-"
                        + digest({"mid": mid, "source": measurement["content_sha256"]}),
                        "kind": "convert_same_quantity",
                        "owner": "M08",
                        "measurement_ids": [mid],
                        "property_id": pid,
                        "reason_issue_keys": [issue["issue_key"]],
                        "status": "pending",
                        "postcheck": "not_checked",
                    }
                )
        cautions = source_cautions.get(mid, [])
        # Only explicit upstream source restrictions affect adoption. No magnitude,
        # typical range, bibliography coverage or missing optional errors here.
        check = (source_checks or {}).get(mid)
        adoption = 100 if check and check.get("state") == "checked" else None
        if adoption is None:
            code = (
                "source_restrictions_not_checked" if not check else "source_restrictions_unresolved"
            )
            issues.append(
                {
                    "issue_key": digest({"rule": code, "measurement": mid}),
                    "rule_id": code,
                    "category": "check_failure",
                    "measurement_ids": [mid],
                    "property_id": pid,
                    "state": "open",
                    "message": code,
                    "impact": {"dimension": "adoption", "level": None, "reason": code},
                }
            )
        for caution in cautions:
            level = caution.get("level")
            if level not in {0, 50, 100, None}:
                raise ValueError("unapproved adoption score")
            if level is None:
                adoption = None
            elif adoption is not None:
                adoption = min(adoption, level)
            issues.append(caution)
        overall = min(delivery, adoption) if delivery is not None and adoption is not None else None
        record = {
            "measurement_id": mid,
            "property_id": pid,
            "source_id": source,
            "delivery": delivery,
            "adoption": adoption,
            "overall": overall,
            "derived_ref": output["derived_id"] if output else None,
        }
        records.append(record)
        groups[(pid, source_groups.get(mid, source_groups.get(source, source)))].append(record)
    group_results = []
    for (pid, group_id), members in sorted(groups.items()):
        known = all(m["overall"] is not None for m in members)
        group_results.append(
            {
                "property_id": pid,
                "group_id": group_id,
                "measurement_ids": [m["measurement_id"] for m in members],
                'source_ids': sorted({m['source_id'] for m in members}),
                "overall": min(m["overall"] for m in members) if known else None,
                "delivery": min(m["delivery"] for m in members)
                if all(m["delivery"] is not None for m in members)
                else None,
                "adoption": min(m["adoption"] for m in members)
                if all(m["adoption"] is not None for m in members)
                else None,
                "independence": "not_asserted",
            }
        )
    properties = []
    for pid in selected_property_ids:
        eligible = [
            g for g in group_results if g["property_id"] == pid and g["overall"] is not None
        ]
        def mean(key):
            applicable = [g for g in group_results if g['property_id'] == pid and g[key] is not None]
            return float(sum(Decimal(g[key]) for g in applicable) / len(applicable)) if applicable else None
        properties.append(
            {
                "property_id": pid,
                "overall": mean("overall"),
                "delivery": mean("delivery"),
                "adoption": mean("adoption"),
                "evaluated_groups": len(eligible),
                "unassessed_groups": len(
                    [g for g in group_results if g["property_id"] == pid and g["overall"] is None]
                ),
                'dimension_coverage': {key: {'evaluated': sum(g[key] is not None for g in group_results if g['property_id'] == pid),
                    'unknown': sum(g[key] is None for g in group_results if g['property_id'] == pid)} for key in ('delivery', 'adoption')},
            }
        )
    evaluated = [p for p in properties if p["overall"] is not None]
    def average(key):
        applicable = [p for p in properties if p[key] is not None]
        return sum(p[key] for p in applicable) / len(applicable) if applicable else None
    status = (
        "no_data"
        if not records
        else "not_evaluated"
        if not evaluated
        else "partial"
        if any(g["overall"] is None for g in group_results)
        else "complete"
    )
    return {
        "schema_version": "QualityReport/2",
        "report_id": "quality-" + digest({"snapshot": snapshot_ref, "phase": phase}),
        "input_ref": snapshot_ref,
        "phase": phase,
        "status": status,
        "measurements": records,
        "groups": group_results,
        "properties": properties,
        "overall_score": average("overall") if phase == "final" else None,
        "dimensions": {"delivery": average("delivery"), "adoption": average("adoption")},
        "score_scope": {
            "selected_property_count": len(selected_property_ids),
            "evaluated_property_count": len(evaluated),
            "eligible_group_count": len(group_results),
            "evaluated_group_count": sum(g["overall"] is not None for g in group_results),
            "unassessed_group_refs": [g["group_id"] for g in group_results if g["overall"] is None],
        },
        "issues": issues,
        "processing_items": processing,
        "explanation": "依据已核查条件评价处理后可用性，不代表科学正确率。性质等权；已知同源组只贡献一次。",
    }
