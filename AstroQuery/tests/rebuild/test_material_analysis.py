from copy import deepcopy

import pytest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError

from tests.rebuild.test_property_insights import example, reply


def test_material_unit_cannot_pull_other_source_records():
    from astroquery_ai.science.material_analysis import scope_unit
    body, spec, unit = example()
    second = deepcopy(body['measurements'][0])
    second['measurement_id'] = 'foreign'
    second['source_ref'] = {'id': 'foreign-source'}
    body['measurements'].append(second)
    body['sources'].append({'source_id': 'foreign-source', 'title': 'Foreign'})
    pid = unit['property_id']
    mid = body['measurements'][0]['source_ref']['id']
    selected, _ = scope_unit(body, spec, None, mid, pid, 'material')
    assert 'foreign' not in [r['measurement_id'] for r in selected['measurements']]
    comparison, _ = scope_unit(body, spec, None, mid, pid, 'property_comparison')
    assert 'foreign' in [r['measurement_id'] for r in comparison['measurements']]


def test_recommendations_must_reference_real_values_and_do_not_default_high_confidence():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    response = reply(unit)
    response['recommendations'] = {'benchmark': {'recommended_value': 'FAKE 10.51',
        'confidence_level': 'high', 'reason': 'No saved record reference'}}
    result = validate_supplement(response, unit)
    assert not result['recommendations'].get('benchmark')
    assert result['sections']['found']
    assert result['validation_issues']
    mid = unit['measurements'][0]['measurement_id']
    response['recommendations']['benchmark'] = {'measurement_ids': [mid],
        'evidence_ids': ['synthetic-evidence'], 'claim_ids': [],
        'reason': '只在这条记录保存的测量条件下参考。'}
    result = validate_supplement(response, unit)
    reference = result['recommendations']['benchmark']
    assert reference['measurement_id'] == mid
    assert reference['source_value'] == unit['measurements'][0]['source_value']
    assert reference['confidence_level'] == 'not_assessed'
    assert 'recommended_value' not in reference


def test_suggestions_and_formulas_reject_foreign_references():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    response = reply(unit)
    response['recommendations'] = {'data_cleaning': [{'rule': 'Wrong', 'action_type': 'exclude',
        'rationale': '必须排除', 'measurement_ids': ['foreign'], 'evidence_ids': ['synthetic-evidence'],
        'claim_ids': []}], 'application_guidance': [{'scenario': 'Invented', 'guidance': 'Unknown theory',
        'claim_ids': ['foreign-claim'], 'formula': 'FAKE'}]}
    result = validate_supplement(response, unit)
    assert not result['recommendations'].get('data_cleaning')
    assert not result['recommendations'].get('application_guidance')
    assert len(result['validation_issues']) >= 2


def test_formula_is_resolved_from_saved_knowledge_instead_of_model_text():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    cid = unit['claims'][0]['claim']['claim_id']
    unit['claims'][0]['raw_entry'] = {'formula': 'F = ma'}
    response = reply(unit)
    response['recommendations'] = {'application_guidance': [{'scenario': '既有理论',
        'guidance': '在保存的条件范围内应用。', 'measurement_ids': [], 'evidence_ids': [],
        'claim_ids': [cid], 'formula': 'FAKE'}]}
    item, = validate_supplement(response, unit)['recommendations']['application_guidance']
    assert item['formula'] == 'F = ma'


def test_uncited_scenario_cannot_acquire_implicit_first_measurement():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    response = reply(unit)
    response['recommendations'] = {'application_guidance': [{'guidance': 'Uncited advice',
        'measurement_ids': [], 'evidence_ids': [], 'claim_ids': []}]}
    result = validate_supplement(response, unit)
    assert result['recommendations']['application_guidance'] == []
    assert result['validation_issues']


def test_exclusion_cannot_broaden_targets_to_another_records_evidence():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    other = deepcopy(unit['measurements'][0])
    other['measurement_id'] = 'other'
    other['source_evidence'] = [{'evidence_id': 'other-evidence', 'raw_text': 'other only'}]
    unit['measurements'].append(other)
    response = reply(unit)
    response['recommendations'] = {'data_cleaning': [{'action_type': 'exclude', 'rationale': '排除目标A',
        'measurement_ids': [unit['measurements'][0]['measurement_id']],
        'evidence_ids': ['other-evidence'], 'claim_ids': []}]}
    result = validate_supplement(response, unit)
    assert result['recommendations']['data_cleaning'] == []
    assert result['validation_issues']


def test_invalid_wire_advice_does_not_erase_valid_sibling_or_seal_complete():
    from astroquery_ai.science.material_analysis import validate_supplement
    from astroquery_ai.science import property_insights as cards
    from astroquery_ai.science.insight_inputs import explanation_wire
    body, spec, unit = example()
    _, bindings = cards.model_input(unit, body, spec)
    response = reply(unit)
    cid = unit['claims'][0]['claim']['claim_id']
    good = {'guidance': '在已有条件范围内使用。', 'measurement_ids': [], 'evidence_ids': [], 'claim_ids': [cid]}
    response['recommendations'] = {'application_guidance': [good, deepcopy(good)]}
    wire = explanation_wire(response, bindings)
    wire['recommendations']['application_guidance'][1]['claim_ids'] = ['K999']
    result = validate_supplement(wire, unit, bindings)
    assert len(result['recommendations']['application_guidance']) == 1
    assert result['validation_issues']


def test_supplement_prompt_has_one_strict_reference_contract_and_no_unbound_formula_example():
    from astroquery_ai.science.material_analysis import supplement_input
    from astroquery_ai.science import property_insights as cards
    body, spec, unit = example()
    packed, _ = cards.model_input(unit, body, spec)
    original = cards.unpack_materials(packed)
    prompt = cards.unpack_materials(supplement_input(packed, 'material'))
    assert prompt['record_index'] == original['record_index']
    rec = prompt['response_example_protocol_only']['recommendations']
    assert rec == {'benchmark': None, 'data_cleaning': [], 'application_guidance': []}
    assert '推荐基准采纳值' not in prompt['instruction']
    assert '联立解算LaTeX公式' not in prompt['instruction']
    for field in ('benchmark', 'data_cleaning', 'application_guidance'):
        assert set(('measurement_ids', 'evidence_ids', 'claim_ids')) <= set(prompt['recommendation_reference_contract'][field]['fields'])


def test_reading_accepts_section_aliases_and_singular_explicit_citations():
    from astroquery_ai.science.material_analysis import validate_supplement
    _, _, unit = example()
    row = reply(unit)['found'][0]
    response = {'observations': [row], 'recommendations': {'application_guidance': [{
        'text': '保留这条已有理论作为有条件的参考。', 'claim_id': unit['claims'][0]['claim']['claim_id']}]}}
    result = validate_supplement(response, unit)
    assert result['sections']['found']
    assert result['recommendations']['application_guidance'][0]['claim_ids'] == [unit['claims'][0]['claim']['claim_id']]


def test_unverified_advice_is_preserved_without_inventing_a_reference_or_numeric_benchmark():
    from astroquery_ai.science.material_analysis import validate_supplement, usable
    _, _, unit = example()
    response = reply(unit)
    response['recommendations'] = {'benchmark': {'reason': '保留原报测量进行有条件对比。', 'recommended_value': 'FAKE 10.51'}}
    result = validate_supplement(response, unit)
    assert not result['recommendations'].get('benchmark')
    assert result['unverified_advice'][0]['text'] == '保留原报测量进行有条件对比。'
    assert usable(result)


def test_complete_json_fields_are_salvaged_without_inventing_truncated_text():
    from astroquery_ai.science.material_analysis import recover_json_fields
    raw = '{"found":[{"text":"complete saved text","measurement_ids":["M1"]}],"uses":[{"text":"unfinished'
    result = recover_json_fields(raw)
    assert result['found'][0]['text'] == 'complete saved text'
    assert result.get('uses', []) == []


def test_final_synthesis_reuses_every_verified_batch_and_retains_full_reference_register():
    from astroquery_ai.science.material_analysis import synthesis_reading_input
    from astroquery_ai.science import property_insights as cards
    rows = [{'measurement_id': f'M{i}', 'source_label': 'S1', 'evidence_ids': [f'E{i}'],
             'source_value': {'raw_value': str(i)}, 'saved_interpretations': ['already read source']} for i in range(1, 501)]
    notes = [{'measurement_ids': [row['measurement_id'] for row in rows[:250]], 'sections': {'found': [{'text': 'First fully read scope'}]}},
             {'measurement_ids': [row['measurement_id'] for row in rows[250:]], 'sections': {'found': [{'text': 'Second fully read scope'}]}}]
    body = {'record_index': rows, 'original_materials': [{'evidence_id': f'E{i}', 'raw_text': 'already read'} for i in range(1, 501)],
            'batch_notes': notes, 'batch_coverage': [{'measurement_ids': note['measurement_ids'], 'status': 'generated'} for note in notes],
            'knowledge': [{'text': 'Exact frozen knowledge'}]}
    compact = cards.unpack_materials(synthesis_reading_input(cards.pack_materials(body)))
    assert compact['record_index_columns'] == ['measurement_id', 'source_label', 'evidence_ids']
    assert [r[0] for r in compact['record_index']] == [r['measurement_id'] for r in rows]
    assert compact['batch_notes'] == notes
    assert compact['batch_coverage'] == body['batch_coverage']
    assert compact['knowledge'] == body['knowledge']
    assert compact['record_index'][499][2] == ['E500']
    assert set(compact['original_materials']['additional_evidence_ids']) | {eid for row in compact['record_index'] for eid in row[2]} == {f'E{i}' for i in range(1, 501)}
    assert len(canonical(compact)) < len(canonical(body))


def test_final_synthesis_never_hides_unread_records():
    from astroquery_ai.science.material_analysis import synthesis_reading_input
    from astroquery_ai.science import property_insights as cards
    body = {'record_index': [{'measurement_id': 'M1'}, {'measurement_id': 'M2'}],
            'batch_notes': [], 'batch_coverage': [{'measurement_ids': ['M1'], 'status': 'generated'}]}
    with pytest.raises(DomainError, match='覆盖'):
        synthesis_reading_input(cards.pack_materials(body))
