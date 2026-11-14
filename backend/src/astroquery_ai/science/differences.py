"""Comparison prerequisites and lightweight summaries using carried context only."""

from collections import defaultdict
from decimal import Decimal

from astroquery_ai.runtime.codec import digest, content_hash
from astroquery_ai.registry.science_conditions import binding_condition_hashes

PRODUCER_VERSION = 'result-comparison-1'


def result_comparisons(measurements, derived, contexts, bindings, snapshot_ref, science_checks, source_statements=None):
    """Display all admitted results; numeric coordinates and strict comparison
    are distinct qualifications. No new scientific verdict or source read.
    """
    outputs = {d['measurement_id']: d for d in derived}
    contexts = {c['measurement_ref']['id']: c for c in contexts}
    bindings = {b['property_id']: b for b in bindings}
    checks = {c['content_sha256']: c for c in science_checks or []}
    units = {}
    statements = {s['statement_id']: s for s in source_statements or []}
    for record in measurements:
        mid, pid = record['measurement_id'], record['property_ref']['id']
        binding = bindings[pid]
        context = contexts.get(mid, {})
        output = outputs.get(mid) or {}
        check = checks.get((output.get('scientific_condition_ref') or {}).get('content_sha256'))
        if (check and check['source_hash'] == record['content_sha256']
                and check['science_record_hash'] in binding_condition_hashes(binding)):
            from .context_views import checked_context
            context = checked_context(context, check)
        conditions = {c['key']: c for c in context.get('conditions', [])}
        identity_keys = [c['key'] for c in binding['definition']['measurement_conditions_schema']
                         if c.get('required_for_identity')]
        defining = {key: {k: conditions.get(key, {}).get(k) for k in ('state', 'value')} for key in identity_keys}
        key = digest({'target': record['target_ref'], 'definition': record['property_ref'],
                      'qualifiers': binding['definition'].get('definition_qualifiers', {}), 'defining': defining})
        unit = units.setdefault(key, {'group_id': key, 'property_id': pid, 'target_ref': record['target_ref'],
            'definition_ref': record['property_ref'], 'definition_qualifiers': binding['definition'].get('definition_qualifiers', {}),
            'measurement_ids': [], 'rows': [], 'coordinate_groups': [], 'scope': 'whole_snapshot',
            'meaning': 'admitted_results_side_by_side_not_strict_scientific_comparability',
            'cause': 'unknown', 'explanation': '现有证据不足以解释差异',
            'author_statements': [],
            'strict_comparison': 'see_comparison_projection_and_limitations'})
        unit['measurement_ids'].append(mid)
        coordinate_reason = None
        if output.get('main_state') != 'ready':
            coordinate_reason = 'processed_main_not_ready_show_native_report'
        elif output.get('source_representation_hash') != record['content_sha256']:
            coordinate_reason = 'processed_coordinate_not_bound_to_source_version'
        elif output.get('limit') != 'none' or output.get('value_typed', {}).get('kind') not in {'real', 'integer'}:
            coordinate_reason = 'not_a_scalar_point_coordinate'
        elif output.get('output_profile_ref') != {k: binding['output_profile'].get(v) for k, v in
                [('id', 'profile_id'), ('version', 'version'), ('content_sha256', 'content_sha256')]}:
            coordinate_reason = 'target_profile_not_confirmed'
        elif 'target' not in output.get('coordinate_units', {}):
            coordinate_reason = 'target_unit_not_confirmed'
        elif any(c['state'] not in {'known', 'not_applicable'} for c in defining.values()):
            coordinate_reason = 'defining_quantity_context_unresolved'
        row = {'measurement_id': mid, 'source_ref': record['source_ref'],
            'source_measurement_ref': {'id': mid, 'version': record['revision'], 'content_sha256': record['content_sha256']},
            'context_ref': record['context_ref'], 'uncertainty': record['uncertainty'],
            'native_unit': record['unit'], 'raw_value': record['raw_value'], 'source_value': record['value'],
            'limit': record['limit'], 'processed': output,
            'conditions': context.get('conditions', []), 'lineage_refs': record.get('lineage_refs', []),
            'numeric_relation_state': 'eligible_common_coordinate' if coordinate_reason is None else 'not_evaluated',
            'numeric_relation_reason': coordinate_reason}
        unit['rows'].append(row)
        for reference in context.get('source_statements', []):
            statement = statements.get(reference['id'])
            if (statement and statement.get('kind') == 'author_explanation'
                    and content_hash(statement) == reference['content_sha256']
                    and statement.get('measurement_id') == mid and statement.get('source_ref') == record['source_ref']
                    and statement.get('raw_quote')):
                unit['author_statements'].append({'statement_ref': reference, 'measurement_ids': [mid],
                    'attribution': 'author_reported', 'raw_quote': statement['raw_quote'], 'page': statement.get('page')})
        if coordinate_reason is None:
            coordinate = {'profile_ref': output['output_profile_ref'], 'unit': output['coordinate_units']['target'],
                          'value_kind': output['value_typed']['kind'], 'limit': 'none'}
            coordinate_id = digest(coordinate)
            group = next((g for g in unit['coordinate_groups'] if g['coordinate_id'] == coordinate_id), None)
            if group is None:
                group = {'coordinate_id': coordinate_id, 'coordinate': coordinate, 'measurement_ids': []}
                unit['coordinate_groups'].append(group)
            group['measurement_ids'].append(mid)
    for unit in units.values():
        for group in unit['coordinate_groups']:
            values = {digest(semantic_value(outputs[mid]['value_typed'])) for mid in group['measurement_ids']}
            group['value_relation'] = 'single_value' if len(group['measurement_ids']) < 2 else 'same_reported_numbers' if len(values) == 1 else 'different_reported_numbers'
            group['significance'] = 'not_assessed'
            group['strict_comparability_asserted'] = False
    return {'schema_version': 'ResultComparison/1', 'snapshot_ref': snapshot_ref, 'groups': list(units.values()),
        'measurement_count': len(measurements), 'model_calls': 0, 'additional_source_reads': 0}


def select_result_comparisons(report, selected):
    """An export subset keeps references and recomputes only numeric counts.

    This never changes source eligibility, conditions, or the sealed report.
    """
    from copy import deepcopy
    result = deepcopy(report)
    groups = []
    for group in result['groups']:
        group['measurement_ids'] = [m for m in group['measurement_ids'] if m in selected]
        if not group['measurement_ids']:
            continue
        group['scope'] = 'export_selection'
        group['rows'] = [r for r in group['rows'] if r['measurement_id'] in selected]
        group['author_statements'] = [s for s in group.get('author_statements', []) if selected.intersection(s['measurement_ids'])]
        rows = {r['measurement_id']: r for r in group['rows']}
        coordinates = []
        for coordinate in group['coordinate_groups']:
            coordinate['measurement_ids'] = [m for m in coordinate['measurement_ids'] if m in selected]
            if not coordinate['measurement_ids']:
                continue
            values = {digest(semantic_value(rows[mid]['processed']['value_typed'])) for mid in coordinate['measurement_ids']}
            coordinate['value_relation'] = 'single_value' if len(coordinate['measurement_ids']) < 2 else 'same_reported_numbers' if len(values) == 1 else 'different_reported_numbers'
            coordinates.append(coordinate)
        group['coordinate_groups'] = coordinates
        groups.append(group)
    result.update(groups=groups, measurement_count=sum(len(g['measurement_ids']) for g in groups), scope='export_selection')
    return result


def semantic_value(value):
    """Equality follows numeric meaning, while original precision stays intact."""
    if isinstance(value, dict):
        return {k: semantic_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [semantic_value(v) for v in value]
    if isinstance(value, str):
        try:
            number = Decimal(value)
            if number.is_finite():
                return str(number.normalize()) if number else "0"
        except __import__("decimal").InvalidOperation:
            pass
    return value


def compare(
    measurements: list[dict],
    derived: list[dict],
    contexts: list[dict],
    bindings: list[dict],
    snapshot_ref: dict,
    source_statements: list[dict] | None = None,
    science_checks: list[dict] | None = None,
) -> dict:
    outputs = {d["measurement_id"]: d for d in derived}
    context_map = {c["measurement_ref"]["id"]: c for c in contexts}
    by_property = {b["property_id"]: b for b in bindings}
    science_by_hash = {c["content_sha256"]: c for c in science_checks or []}
    groups, limitations = defaultdict(list), []
    for record in measurements:
        mid, pid = record["measurement_id"], record["property_ref"]["id"]
        binding, output = by_property[pid], outputs.get(mid)
        if not output or output["main_state"] != "ready":
            limitations.append({"measurement_ids": [mid], "reason": "target_main_not_ready"})
            continue
        required = [
            c["key"]
            for c in binding["definition"]["measurement_conditions_schema"]
            if c["required_for_comparison"]
        ]
        context = context_map.get(mid)
        conditions = {c["key"]: c for c in context["conditions"]} if context else {}
        if binding.get("science_ref"):
            check = science_by_hash.get((output.get("scientific_condition_ref") or {}).get("content_sha256"))
            prerequisite = (check or {}).get("comparison_prerequisites", {})
            if (not check or check["source_hash"] != record["content_sha256"]
                    or check['science_record_hash'] not in binding_condition_hashes(binding)
                    or prerequisite.get("state") != "identified"):
                limitations.append({"measurement_ids": [mid], "reason": "scientific_comparison_prerequisites_unresolved",
                    "missing_requirements": prerequisite.get("missing_context_keys", []),
                    "detail": prerequisite.get("reason", "comparison_prerequisites_not_checked")})
                continue
            # The reviewed per-source prerequisite selects applicable contexts;
            # legacy definition flags must not turn specimen-only metadata into
            # a universal AND across unrelated source branches.
            required = sorted(set(prerequisite["required_context_keys"]))
            from .context_views import checked_context
            context = {**checked_context(context or {}, check), 'comparison_keys': required}
            conditions = {c['key']: c for c in context['conditions']}
        missing = [key for key in required if conditions.get(key, {}).get("state") not in {'known', 'not_applicable'}]
        if missing:
            limitations.append(
                {
                    "measurement_ids": [mid],
                    "reason": "missing_comparison_requirements",
                    "missing_requirements": missing,
                }
            )
            continue
        # None vs no requirements is explicit in approved definition. Unknowns
        # above are never grouped just because two records both omit a condition.
        key = digest(
            {
                "property": pid,
                "target": record['target_ref'],
                "definition": record['property_ref'],
                "profile": binding["output_profile"],
                "conditions": {k: {'state': conditions[k]['state'], 'value': semantic_value(conditions[k].get('value'))} for k in required},
                "kind": output["value_typed"]["kind"],
                "limit": output["limit"],
            }
        )
        groups[(pid, key)].append((record, output, context))
    summaries, projection = [], []
    for (pid, key), records in sorted(groups.items()):
        projection.append(
            {
                "group_id": key,
                "property_id": pid,
                "measurement_ids": [r["measurement_id"] for r, _, _ in records],
                "value_kind": records[0][1]["value_typed"]["kind"],
                "limit": records[0][1]["limit"],
                "status": "comparable",
                "condition_basis": [
                    {"key": c["key"], "value": c["value"]}
                    for c in (records[0][2] or {}).get("conditions", [])
                    if c["state"] == "known" and c["key"] in (records[0][2] or {}).get("comparison_keys", [c["key"]])
                ],
            }
        )
        if len(records) < 2:
            continue
        values = [o["value_typed"] for _, o, _ in records]
        # Only numeric schemas normalize number spelling. Category labels such
        # as "001" and "1" remain distinct labels.
        distinct = {
            digest(
                semantic_value(value) if value["kind"] in {"real", "integer", "interval"} else value
            )
            for value in values
        }
        if len(distinct) < 2:
            continue
        summary = {
            "group_id": key,
            "property_id": pid,
            "measurement_ids": [r["measurement_id"] for r, _, _ in records],
            "distinct_reported_values": len(distinct),
            "status": "different_measurements",
            "cause": "unknown",
            "author_statement_refs": [],
            "source_relationships": "preserve_lineage_not_independence",
            'uncertainty_refs': [context['uncertainty_ref'] for _, _, context in records
                                 if context and context.get('uncertainty_ref')],
            'context_refs': [r['context_ref'] for r, _, _ in records],
        }
        statements = {s['statement_id']: s for s in source_statements or []}
        author_statements, condition_facts = [], []
        for record, _, context in records:
            for condition in (context or {}).get('conditions', []):
                if condition['state'] == 'known':
                    condition_facts.append({'measurement_ids': [record['measurement_id']],
                        'condition_key': condition['key'], 'value': condition['value'],
                        'evidence_refs': condition.get('evidence_refs', []), 'scope': 'measurement'})
            for reference in (context or {}).get('source_statements', []):
                statement = statements.get(reference['id'])
                if (not statement or statement.get('kind') != 'author_explanation'
                        or content_hash(statement) != reference['content_sha256']
                        or statement['measurement_id'] != record['measurement_id']
                        or statement['source_ref'] != record['source_ref'] or not statement.get('raw_quote')):
                    continue
                author_statements.append({'statement_ref': reference, 'quote_ref': reference,
                    'applies_to_measurement_ids': [record['measurement_id']],
                    'comparison_subjects': {'scope': 'source_statement_only', 'source_ref': record['source_ref']},
                    'attribution': 'author_reported', 'quote': statement['raw_quote'],
                    'page': statement.get('page')})
        summary['author_statement_refs'] = [a['statement_ref'] for a in author_statements]
        summary['explanation'] = {'condition_facts': condition_facts, 'author_statements': author_statements,
            'whole_group_cause': 'unknown',
            'unknown_reasons': ['no_group_cause_established'] if author_statements else
                               ['context_not_checked' if source_statements is None else 'no_applicable_statement']}
        if all(v["kind"] == "real" for v in values) and all(
            o["limit"] == "none" for _, o, _ in records
        ):
            numbers = [Decimal(v["value"]) for v in values]
            summary["range"] = {
                "min": str(min(numbers)),
                "max": str(max(numbers)),
                "meaning": "descriptive_span_not_uncertainty",
            }
        summaries.append(summary)
    records_by_id = {r['measurement_id']: r for r in measurements}
    for limitation in limitations:
        views = []
        for mid in limitation['measurement_ids']:
            record = records_by_id[mid]
            context = context_map.get(mid, {})
            output = outputs.get(mid, {})
            check = science_by_hash.get((output.get('scientific_condition_ref') or {}).get('content_sha256'))
            if check and check['source_hash'] == record['content_sha256'] and check['science_record_hash'] in binding_condition_hashes(by_property[record['property_ref']['id']]):
                from .context_views import checked_context
                context = checked_context(context, check)
            views.append({'measurement_id': mid, 'property_id': record['property_ref']['id'],
                'context_ref': record['context_ref'], 'conditions': [{k: c.get(k) for k in ('key', 'state', 'value', 'reason', 'evidence_refs', 'interpretation_origin')}
                    for c in context.get('conditions', [])]})
        limitation['condition_views'] = views
    return {
        "schema_version": "DifferenceReport/1",
        "report_id": "difference-" + digest({'snapshot': snapshot_ref, 'producer': PRODUCER_VERSION}),
        "producer_version": PRODUCER_VERSION,
        "snapshot_ref": snapshot_ref,
        "groups": summaries,
        "limitations": limitations,
        "model_calls": 0,
        "additional_source_reads": 0,
        "result_comparisons": result_comparisons(measurements, derived, contexts, bindings, snapshot_ref, science_checks, source_statements),
        "comparison_projection": {
            "schema_version": "ComparisonProjection/1",
            "snapshot_ref": snapshot_ref,
            "groups": projection,
            "limitations": limitations,
        },
    }
