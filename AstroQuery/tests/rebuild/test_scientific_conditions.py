"""Synthetic operation-gate checks; these do not qualify real source semantics."""
from copy import deepcopy
import pytest

from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.science.scientific_conditions import checked_semantics, operation_permission, restrict_components
from tests.rebuild.factories import measurement


def test_count_coordinate_does_not_authorize_rates_or_other_dimensionless_measurands():
    from astroquery_ai.science.unit_declarations import arithmetic_coordinate_units
    profile={'unit':{'kind':'dimensionless','semantic_kind':'count'},'representation':{'kind':'linear'}}
    record={'unit':'ct','representation':'linear'}
    assert arithmetic_coordinate_units(record,profile)==('1','1')
    assert record['unit']=='ct'
    assert arithmetic_coordinate_units({**record,'unit':'ct/s'},profile)==('ct/s','1')
    assert arithmetic_coordinate_units(record,{**profile,'unit':{'kind':'dimensionless','semantic_kind':'ratio'}})==('ct','1')


@pytest.mark.parametrize('semantic_kind',['count','count under exact source definition'])
def test_count_missing_unit_declaration_is_typed_and_keeps_original_absence(semantic_kind):
    from astroquery_ai.science.unit_declarations import count_unit_declaration
    from astroquery_ai.runtime.models import SourceUnitDeclaration
    from tests.rebuild.factories import ref
    binding={'output_profile':{'unit':{'kind':'dimensionless','semantic_kind':semantic_kind}}}
    source={'kind':'catalog','table_id':'SYNTHETIC/T','metadata':{'columns':[{'name':'N','unit_text':None,'description':'SYNTHETIC selected member count'}]}}
    proposal={'column':'N','row':0,'value':{'kind':'integer','value':'37'},'unit':None,'representation':'linear',
              'quantity_match':'exact','catalog_quantity_evidence':['N']}
    declared=count_unit_declaration(source,proposal,binding,artifact_ref=ref('SYNTHETIC artifact'))
    checked=SourceUnitDeclaration.model_validate(declared)
    assert checked.canonical_symbol=='1' and checked.source_literal is None and checked.raw_unit_text is None
    assert checked.artifact_ref.id=='SYNTHETIC artifact'


def test_missing_component_repair_cannot_overwrite_good_main_or_error_siblings():
    from astroquery_ai.science.scientific_conditions import merge_semantic_repair
    original = {'checks': [{'key': 'main', 'state': 'supported'}],
        'uncertainty': [{'component_id': 'good', 'disposition': 'eligible'}]}
    checked = {'checks': {'main': original['checks'][0]}, 'uncertainty': {'good': original['uncertainty'][0]}}
    repair = {'checks': [{'key': 'main', 'state': 'contradicted'}],
        'uncertainty': [{'component_id': 'missing', 'disposition': 'retain_unknown'}]}
    merged = merge_semantic_repair(original, checked, repair, [], ['missing'])
    assert merged['checks'] == original['checks']
    assert merged['uncertainty'] == [original['uncertainty'][0], repair['uncertainty'][0]]
    repair['uncertainty'].append({'component_id': 'good', 'disposition': 'retain_unknown'})
    assert merge_semantic_repair(original, checked, repair, [], ['missing']) == original


def test_context_citation_repair_preserves_other_facts_and_revalidates_source():
    from astroquery_ai.science.scientific_conditions import merge_semantic_repair
    record, science, binding, spans, response = inputs()
    science['context_contracts'] = [{'key': 'band'}, {'key': 'method'}]
    response['contexts'] = [
        {'key': 'band', 'state': 'known', 'value': 'SYNTHETIC-X', 'anchors': ['reported_context:band']},
        {'key': 'method', 'state': 'known', 'value': 'SYNTHETIC-M', 'anchors': ['s']}]
    response['comparison_prerequisites'] = {'state': 'identified', 'required_context_keys': ['band'], 'anchors': []}
    checked = checked_semantics(response, science, record, spans)
    assert checked['contexts']['band']['state'] == 'unknown'
    repair = {'contexts': [{'key': 'band', 'state': 'known', 'value': 'SYNTHETIC-X', 'anchors': ['s']}],
        'comparison_prerequisites': {'state': 'identified', 'required_context_keys': ['band'], 'anchors': ['s']},
        'checks': [{'key': 'identity', 'state': 'contradicted'}]}
    merged = merge_semantic_repair(response, checked, repair, [], [], ['band'], True)
    assert merged['checks'] == response['checks']
    assert next(c for c in merged['contexts'] if c['key'] == 'method') == response['contexts'][1]
    rechecked = checked_semantics(merged, science, record, spans)
    assert rechecked['comparison_prerequisites']['state'] == 'identified'
    # Replacing a malformed citation is still subject to exact source binding.
    repair['contexts'][0]['anchors'] = ['invented-source']
    invalid = merge_semantic_repair(response, checked, repair, [], [], ['band'], True)
    assert checked_semantics(invalid, science, record, spans)['comparison_prerequisites']['state'] == 'unresolved'
    repair['contexts'].append({'key': 'method', 'state': 'known', 'value': 'OTHER', 'anchors': ['s']})
    assert merge_semantic_repair(response, checked, repair, [], [], ['band']) == response


def test_main_context_recheck_cannot_fill_unknown_comparison_context_or_replace_other_verdicts():
    from astroquery_ai.science.scientific_conditions import merge_semantic_repair
    original = {'checks': [{'key': 'identity', 'state': 'supported'}, {'key': 'main_context', 'state': 'unknown'}],
        'contexts': [{'key': 'timing', 'state': 'unknown', 'value': None}],
        'comparison_prerequisites': {'state': 'unresolved', 'required_context_keys': ['timing']},
        'uncertainty': []}
    checked = {'checks': {c['key']: c for c in original['checks']}, 'uncertainty': {}}
    repair = {'checks': [{'key': 'main_context', 'state': 'supported'}],
        'contexts': [{'key': 'timing', 'state': 'known', 'value': 'INVENTED'}]}
    merged = merge_semantic_repair(original, checked, repair, ['main_context'], [])
    assert merged['checks'] == [original['checks'][0], repair['checks'][0]]
    assert merged['contexts'] == original['contexts']
    assert merged['comparison_prerequisites'] == original['comparison_prerequisites']


def inputs():
    record = measurement(value="2")
    record["unit"] = "m"
    record["content_sha256"] = content_hash(record)
    profile_ref = {"id": "synthetic-profile", "version": 1, "content_sha256": "1" * 64}
    requirements = ["source_subject_quantity_evidence_verified", "source_native_main_coordinate_evidenced",
        "source_main_state_interpreted", "source_required_context_verified", "fixed_target_exactly_selected",
        "source_record_and_context_binding_verified", "raw_source_preservation_verified",
        "finite_non_null_main_or_explicit_limit", "same_numerical_coordinate"]
    science = {"record_id": "synthetic-conditions", "version": 1, "profile_ref": profile_ref,
        "required_conditions": [{"key": k} for k in [*requirements, "log_map_documented", "component_semantics_resolved"]],
        "context_contracts": [], "operations": [
            {"operation": "same_value_target", "applies_to": "main_value", "scientific_decision": "allowed_if_conditions", "core_transform_enum": "identity", "requires": requirements},
            {"operation": "log_representation_same_quantity", "applies_to": "main_value", "scientific_decision": "allowed_if_conditions", "core_transform_enum": "logarithmic", "requires": ["log_map_documented"]},
        ]}
    science["content_sha256"] = content_hash(science)
    binding = {"science_ref": {"content_sha256": science["content_sha256"]}, "definition": {"quantity_key": "synthetic-length"},
        "output_profile": {"unit": {"canonical_symbol": "m"}, "representation": {"kind": "linear"}},
        "candidate_projection_receipt": {"source_profile_ref": profile_ref}}
    spans = [{"span_id": "s", "text": "SYNTHETIC exact source quantity, unit, disposition and context."}]
    response = {"checks": [{"key": k, "state": "supported", "anchors": [{"span_id": "s", "quote": "exact source"}]} for k in requirements if k.startswith("source_") and k not in {"source_record_and_context_binding_verified"}]}
    response["checks"] = [i for i in response["checks"] if i["key"] in {"source_subject_quantity_evidence_verified", "source_native_main_coordinate_evidenced", "source_main_state_interpreted", "source_required_context_verified"}]
    return record, science, binding, spans, response


def test_unneeded_predicates_and_optional_error_do_not_block_main():
    record, science, binding, spans, response = inputs()
    semantic = checked_semantics(response, science, record, spans)
    result = operation_permission(science, binding, record, {"kind": "linear"}, semantic, provenance_verified=True)
    assert result["allowed"] and result["operation"] == "same_value_target"
    assert "component_semantics_resolved" not in result["predicate_results"]
    assert "log_map_documented" not in result["predicate_results"]


def test_carried_native_locator_resolves_only_one_existing_source_span():
    record, science, _, spans, response = inputs()
    spans[0]['locator'] = 'p4:l62-86'
    response['checks'][0]['anchors'] = ['p4:l62-86']
    checked = checked_semantics(response, science, record, spans)
    key = response['checks'][0]['key']
    assert checked['checks'][key]['state'] == 'supported'
    assert any(a['resolved_source_span_id'] == 's' for a in checked['anchor_checks'])
    response['checks'][0]['anchors'] = ['p4:l62-87']
    assert checked_semantics(response, science, record, spans)['checks'][key]['state'] == 'unknown'
    response['checks'][0]['anchors'] = ['p4:l62-86']
    spans.append({'span_id': 'another', 'locator': 'p4:l62-86', 'text': 'SYNTHETIC another span'})
    assert checked_semantics(response, science, record, spans)['checks'][key]['state'] == 'unknown'


def test_naked_true_or_unverifiable_quote_never_establishes_semantic_evidence():
    record, science, binding, spans, response = inputs()
    response["checks"][0]["anchors"][0]["quote"] = "fabricated words"
    semantic = checked_semantics(response, science, record, spans)
    result = operation_permission(science, binding, record, {"kind": "linear"}, semantic, provenance_verified=True)
    assert not result["allowed"] and "source_subject_quantity_evidence_verified" in result["missing"]
    response["checks"][0]["anchors"][0]["quote"] = "exact source"
    semantic = checked_semantics(response, science, record, spans)
    assert not operation_permission(science, binding, record, {"kind": "linear"}, semantic, provenance_verified=False)["allowed"]


def test_unresolved_source_state_blocks_numeric_main():
    record, science, binding, spans, response = inputs()
    next(i for i in response["checks"] if i["key"] == "source_main_state_interpreted")["state"] = "unknown"
    result = operation_permission(science, binding, record, {"kind": "linear"}, checked_semantics(response, science, record, spans), provenance_verified=True)
    assert not result["allowed"] and "source_main_state_interpreted" in result["missing"]


def test_selected_immutable_span_and_invalid_auxiliary_comparison_are_independent():
    record, science, binding, spans, response = inputs()
    response['checks'][0]['anchors'] = [{'span_id': 's'}]
    response['comparison_prerequisites'] = {'state': 'not_applicable', 'required_context_keys': []}
    checked = checked_semantics(response, science, record, spans)
    assert checked['comparison_prerequisites']['state'] == 'unresolved'
    assert operation_permission(science, binding, record, {'kind': 'linear'}, checked, provenance_verified=True)['allowed']
    response['checks'][0]['anchors'] = [{'span_id': 'invented'}]
    assert not operation_permission(science, binding, record, {'kind': 'linear'}, checked_semantics(response, science, record, spans), provenance_verified=True)['allowed']


def test_compact_evidence_strings_bind_exact_spans_without_model_quote_reconstruction():
    from astroquery_ai.science.scientific_conditions import source_span_aliases
    record, science, binding, spans, response = inputs()
    alias = next(iter(source_span_aliases(spans)))
    response['checks'][0]['anchors'] = [alias]
    checked = checked_semantics(response, science, record, spans)
    assert checked['checks'][response['checks'][0]['key']]['state'] == 'supported'
    assert checked['anchor_checks'][0]['resolved_source_span_id'] == 's'
    response['checks'][0]['anchors'] = ['s-invented']
    assert not operation_permission(science, binding, record, {'kind': 'linear'}, checked_semantics(response, science, record, spans), provenance_verified=True)['allowed']


def test_cell_display_anchor_requires_exact_field_and_original_literal():
    record, science, binding, spans, response = inputs()
    spans.append({"span_id": "cells", "text": '{"clock":"TDB","epoch":"48442.5000000"}', "origin": "original_source_cells"})
    response["checks"][0]["anchors"] = [{"span_id": "cells", "quote": "epoch: 48442.5000000"}]
    checked = checked_semantics(response, science, record, spans)
    assert checked["checks"][response["checks"][0]["key"]]["state"] == "supported"
    assert any(c["method"] == "exact_structured_cell_display" for c in checked["anchor_checks"])
    response["checks"][0]["anchors"][0]["quote"] = "epoch: 48442.5"
    checked = checked_semantics(response, science, record, spans)
    assert checked["checks"][response["checks"][0]["key"]]["state"] == "unknown"


def test_metadata_quote_can_use_json_display_but_cannot_change_source_null_code():
    record, science, binding, spans, response = inputs()
    spans.append({"span_id": "column", "text": "{'null': 'NaN'}", "column_metadata": {"null": "NaN"}, "origin": "original_column_metadata"})
    response["checks"][0]["anchors"] = [{"span_id": "column", "quote": '"null":"NaN"'}]
    assert checked_semantics(response, science, record, spans)["checks"][response["checks"][0]["key"]]["state"] == "supported"
    response["checks"][0]["anchors"][0]["quote"] = '"null":"0"'
    assert checked_semantics(response, science, record, spans)["checks"][response["checks"][0]["key"]]["state"] == "unknown"


def test_optional_unknown_is_preserved_but_real_math_failure_is_not_erased():
    record, science, binding, spans, response = inputs()
    record["uncertainty"]["components"] = [{"component_id": "c", "interpretation_state": "unresolved"}]
    result = {"main_state": "ready", "status": "partial", "uncertainty_typed": {"components": [{"source_component_id": "c", "status": "unsupported", "output_component": None}]}}
    semantics = {"uncertainty": {"c": {"disposition": "retain_unknown", "reason": "source explicitly does not define it"}}}
    restrict_components(result, record, science, {"operation": "same_value_target"}, semantics)
    assert result["status"] == "ready" and result["uncertainty_typed"]["components"][0]["raw_component_ref"] == "c"
    failed = deepcopy(result)
    failed.update(status="partial")
    failed["uncertainty_typed"]["components"][0]["status"] = "unsupported"
    semantics["uncertainty"]["c"]["disposition"] = "eligible"
    restrict_components(failed, record, science, {"operation": "same_value_target"}, semantics)
    assert failed["status"] == "partial"


def test_scientific_comparison_requires_carried_context_but_not_optional_confidence():
    from astroquery_ai.science.differences import compare
    from tests.rebuild.factories import derived, ref
    first, science, binding, spans, response = inputs()
    second = deepcopy(first)
    second.update(measurement_id='synthetic-other', value={'kind': 'real', 'value': '3'})
    second['content_sha256'] = content_hash(second)
    science['context_contracts'] = [{'key': 'band'}]
    science['content_sha256'] = content_hash(science)
    binding.update(property_id=first['property_ref']['id'], science_ref={'content_sha256': science['content_sha256']})
    binding['definition']['measurement_conditions_schema'] = []
    response.update(contexts=[{'key': 'band', 'state': 'known', 'value': 'SYNTHETIC-X', 'anchors': [{'span_id': 's'}]}],
        comparison_prerequisites={'state': 'identified', 'required_context_keys': ['band'], 'anchors': [{'span_id': 's'}]})
    checks, outputs, contexts = [], [], []
    for record in (first, second):
        check = checked_semantics(response, science, record, spans)
        check['check_id'] = 'SYNTHETIC-check-' + record['measurement_id']
        check['content_sha256'] = content_hash(check)
        checks.append(check)
        output = derived(record)
        output.update(scientific_condition_ref={'content_sha256': check['content_sha256']})
        outputs.append(output)
        contexts.append({'measurement_ref': {'id': record['measurement_id']}, 'conditions': []})
    report = compare([first, second], outputs, contexts, [binding], ref('snapshot'), science_checks=checks)
    assert len(report['groups']) == 1
    assert 'significance' not in report['groups'][0]
    checks[1]['comparison_prerequisites']['state'] = 'unresolved'
    checks[1]['content_sha256'] = content_hash(checks[1])
    outputs[1]['scientific_condition_ref']['content_sha256'] = checks[1]['content_sha256']
    report = compare([first, second], outputs, contexts, [binding], ref('snapshot'), science_checks=checks)
    assert not report['groups'] and report['limitations']
