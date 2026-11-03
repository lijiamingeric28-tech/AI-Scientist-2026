from copy import deepcopy

from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.runtime.calls import input_upper_bound
from astroquery_ai.science.insight_inputs import build_units, explanation_prompt, measurement_input
from astroquery_ai.science.differences import compare
from tests.rebuild.factories import measurement, error_component, ref, derived


def case():
    record = measurement(components=[error_component('SYNTHETIC stat'), error_component(
        'SYNTHETIC sys', role='sys', values={'delta': '0.2'})])
    context = {'measurement_ref': {'id': record['measurement_id'], 'version': 1},
               'conditions': [], 'source_statements': [ref('SYNTHETIC statement')],
               'uncertainty_ref': ref('SYNTHETIC uncertainty')}
    statement = {'statement_id': 'SYNTHETIC statement', 'measurement_id': record['measurement_id'],
        'source_ref': record['source_ref'], 'kind': 'author_explanation', 'text': 'SYNTHETIC method limitation',
        'raw_quote': 'SYNTHETIC author attributes this result to method A only.', 'page': 1}
    context['source_statements'][0]['content_sha256'] = content_hash(statement)
    converted = {**derived(record), 'source_representation_hash': record['content_sha256'],
        'value_typed': {'kind': 'real', 'value': '200'},
        'uncertainty_typed': {'components': [{'source_component_id': 'SYNTHETIC stat', 'delta': '10'},
                                            {'source_component_id': 'SYNTHETIC sys', 'delta': '20'}]}}
    delivery = {'delivery_id': 'SYNTHETIC delivery', 'snapshot_ref': ref('SYNTHETIC snapshot'),
        'measurements': [record], 'contexts': [context], 'derived': [converted],
        'sources': [{'source_id': record['source_ref']['id'], 'title': 'SYNTHETIC source', 'kind': 'paper', 'version_grade': 'preprint'}],
        'evidence_index': [{'evidence_id': record['evidence_refs'][0]['id'], 'raw_text': 'SYNTHETIC original source ' * 25, 'locator': {'page': 1}}],
        'provenance_bundle': {'source_statements': [statement], 'unit_records': [{'unit_id': 'source-unit', 'unit_text': 'm'}]}}
    spec = {'target': {'main_id': 'SYNTHETIC target', 'primary_otype': '*'}, 'properties': [{
        'property_id': record['property_ref']['id'],
        'definition': {'name_cn': '合成长度', 'description': 'SYNTHETIC length', 'measurement_conditions_schema': []},
        'output_profile': {'unit': {'canonical_symbol': 'cm'}, 'representation': {'kind': 'linear'}},
    }]}
    return delivery, spec


def test_missing_theory_keeps_normal_model_fact_explanation_and_sealed_values(tmp_path):
    import asyncio,json
    from tests.rebuild.scenario import application,confirmed_case
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json;captured=[]
        async def respond(**kwargs):
            if kwargs['owner']!='M11':return await ordinary(**kwargs)
            prompt=json.loads(kwargs['messages'][0]['content']);captured.append(prompt)
            unit=prompt['units'][0];mid=unit['measurements'][0]['measurement_id']
            return {'units':[{'unit_id':unit['unit_id'],'numeric_mode':'snapshot_placeholders/1','paragraphs':[
                {'kind':'source_fact','text':'已保留该来源的结果及原报信息；使用时需同时查看其来源条件。',
                 'measurement_ids':[mid],'claim_ids':[],'value_assertions':[]}]}]}, {'attempt_id':'SYNTHETIC source facts'}
        app.models.json=respond
        with app.repository.transaction() as conn:
            conn.execute('INSERT INTO settings VALUES(?,?,1)',('profile:M11',canonical({'state':'validated','synthetic':True})))
        state,_=await confirmed_case(app)
        with app.repository.read() as conn:
            delivery=app.delivery.get(conn,state['task_id'])
            report=app.repository.object(conn,state['task_id'],'insight',state['insight_ref']['id'])
        assert captured and all(not u['claims'] for p in captured for u in p['units'])
        assert any(u['generation_mode']=='model' for u in report['units'])
        assert delivery['measurements'][0]['raw_value']=='0' and state['science_state']=='sealed'
    asyncio.run(run())


def test_model_gets_processed_values_separate_errors_and_same_source_context():
    delivery, spec = case()
    record = delivery['measurements'][0]
    view = measurement_input(delivery, record)
    assert view['source_value']['value']['value'] == '2'
    assert view['processed_value']['value_typed']['value'] == '200'
    assert [(c['role'], c['values']) for c in view['source_uncertainty']['components']] == [
        ('stat', {'delta': '0.1'}), ('sys', {'delta': '0.2'})]
    assert view['source_statements'][0]['raw_quote'].startswith('SYNTHETIC author')
    assert view['source_evidence'][0]['locator'] == {'page': 1}
    delivery['derived'][0]['source_representation_hash'] = 'SYNTHETIC stale input'
    assert measurement_input(delivery, record)['processed_value'] == {'status': 'not_available'}


def test_error_assertion_examples_carry_the_same_required_source_coordinate():
    delivery,spec=case()
    unit=build_units(delivery,spec,[],None)[0]
    prompt=explanation_prompt([unit],delivery,spec)
    choices=prompt['response_constraints'][0]['available_component_keys']
    assert len(choices)==2 and all(c['coordinate']=='source' and c['measurement_id'] for c in choices)
    example=prompt['paragraph_shape']['example_protocol_only']
    assert '"coordinate":"source"' in example and '{{v1}}' in example
    assert '{{e0}}' not in example


def test_model_view_omits_only_repeated_audit_bindings_not_scientific_context():
    delivery, _ = case()
    record = delivery['measurements'][0]
    delivery['contexts'][0]['conditions'] = [
        {'key': 'source_subject_quantity_evidence_verified', 'state': 'not_reported', 'value': None},
        {'key': 'timing_scale', 'state': 'unknown', 'value': None}]
    statement = delivery['provenance_bundle']['source_statements'][0]
    statement.update(artifact_ref=ref('SYNTHETIC artifact'), verification_attempt_id='SYNTHETIC attempt',
                     schema_version='SYNTHETIC statement/1', grants_retrieval=False)
    before = deepcopy(delivery)
    view = measurement_input(delivery, record)
    assert [c['key'] for c in view['conditions']] == ['timing_scale']
    result = view['source_statements'][0]
    assert result['raw_quote'] == statement['raw_quote'] and result['text'] == statement['text']
    assert result['statement_id'] == statement['statement_id'] and result['page'] == statement['page']
    assert 'verification_attempt_id' not in result and 'source_ref' not in result
    assert delivery == before


def test_unresolved_error_can_be_quoted_as_raw_without_becoming_parsed_amplitude():
    import pytest
    from astroquery_ai.science.insight_validation import validate_units
    from astroquery_ai.runtime.errors import DomainError
    delivery, _ = case()
    row = measurement_input(delivery, delivery['measurements'][0])
    error = row['source_uncertainty']['components'][0]
    error.update(values=None, raw_text='4.0e-15', interpretation_state='unresolved')
    unit = {'unit_id': 'SYNTHETIC raw-error unit', 'measurements': [row], 'claims': []}
    assertion = {'measurement_id': row['measurement_id'], 'coordinate': 'source',
        'component_id': error['component_id'], 'value_key': 'raw_text', 'value': '4.0e-15', 'unit': error['unit']}
    p = {'kind': 'usage_limit', 'text': '原误差栏记为4.0e-15，统计角色与置信度仍未知。',
         'measurement_ids': [row['measurement_id']], 'claim_ids': [], 'value_assertions': [assertion]}
    response = {'units': [{'unit_id': unit['unit_id'], 'paragraphs': [p]}]}
    assert validate_units(response, [unit])
    assert error['values'] is None and error['interpretation_state'] == 'unresolved'
    forged = deepcopy(response)
    forged['units'][0]['paragraphs'][0]['value_assertions'][0]['value_key'] = 'delta'
    with pytest.raises(DomainError, match='封口快照'):
        validate_units(forged, [unit])
    forged['units'][0]['paragraphs'][0]['value_assertions'][0].update(value_key='raw_text', value='5.0e-15')
    with pytest.raises(DomainError, match='封口快照'):
        validate_units(forged, [unit])


def test_provisional_other_quantity_epoch_does_not_reenter_explanation_cells():
    delivery, _ = case()
    record = delivery['measurements'][0]
    source = delivery['sources'][0]
    source.update(kind='catalog', table_id='SYNTHETIC/table', metadata={'columns': [
        {'name': 'Main'}, {'name': 'OtherEpoch'}, {'name': 'OwnEpoch'}]})
    delivery['contexts'][0]['conditions'].append({'key': 'SYNTHETIC missing epoch', 'state': 'unknown',
        'value': None, 'reason': 'Other quantity OtherEpoch=50000.000 is present, but this epoch is unknown.'})
    delivery['evidence_index'][0].update(text_origin='original_cells', raw_text=canonical({
        'cells': {'Main': '2.00', 'OtherEpoch': '50000.000', 'OwnEpoch': '40000.000'}, 'columns': []}).decode())
    delivery['provenance_bundle']['interpretations'] = [{
        'interpretation_id': record['interpretation_ref']['id'], 'revision': record['interpretation_ref']['version'],
        'proposal': {'column': 'Main', 'errors': [], 'source_references': [], 'conditions': [
            {'state': 'known', 'raw_text': 'OwnEpoch: 40000.000'}]}}]
    delivery['provenance_bundle']['catalog_column_plans'] = [{'table_id': source['table_id'],
        'plan': {'id_column': 'Name', 'properties': [{'property_id': record['property_ref']['id'],
            'value_column': 'Main', 'context_columns': ['OtherEpoch']}]}}]
    view = measurement_input(delivery, record)
    from astroquery_ai.runtime.codec import loads
    cells = loads(view['source_evidence'][0]['raw_text'])['cells']
    assert cells == {'Main': '2.00', 'OwnEpoch': '40000.000'}
    assert '50000' not in canonical(view).decode()
    assert delivery['contexts'][0]['conditions'][-1]['reason'].startswith('Other quantity')
    assert 'OtherEpoch' in delivery['evidence_index'][0]['raw_text']  # Original evidence stays intact.


def test_long_normal_property_is_split_between_complete_measurements():
    delivery, spec = case()
    row = delivery['measurements'][0]
    for i in range(1, 25):
        clone = deepcopy(row)
        clone['measurement_id'] = 'SYNTHETIC m' + str(i)
        delivery['measurements'].append(clone)
    units = build_units(delivery, spec, [], None, input_limit=10000)
    assert len(units) > 1
    assert {m['measurement_id'] for u in units for m in u['measurements']} == {m['measurement_id'] for m in delivery['measurements']}
    assert all(len(m['source_uncertainty']['components']) == 2 for u in units for m in u['measurements'])
    for unit in units:
        prompt = explanation_prompt([unit], delivery, spec)
        assert prompt['snapshot_ref'] == delivery['snapshot_ref']
        assert input_upper_bound([{'role': 'user', 'content': canonical(prompt).decode()}]) <= 10000


def test_author_explanation_is_source_scoped_not_whole_group_cause():
    delivery, spec = case()
    first = delivery['measurements'][0]
    second = measurement('SYNTHETIC m2', value='3', source='SYNTHETIC different source')
    contexts = [*delivery['contexts'], {'measurement_ref': {'id': second['measurement_id'], 'version': 1}, 'conditions': [], 'source_statements': []}]
    report = compare([first, second], [derived(first), derived(second)], contexts, spec['properties'], delivery['snapshot_ref'],
                     source_statements=delivery['provenance_bundle']['source_statements'])
    explanation = report['groups'][0]['explanation']
    assert report['groups'][0]['cause'] == explanation['whole_group_cause'] == 'unknown'
    assert explanation['author_statements'][0]['applies_to_measurement_ids'] == [first['measurement_id']]
    assert explanation['author_statements'][0]['attribution'] == 'author_reported'
    assert second['measurement_id'] not in explanation['author_statements'][0]['applies_to_measurement_ids']


def test_long_first_property_cannot_starve_other_requested_insights():
    delivery, spec = case()
    original = delivery['measurements'][0]
    for i in range(1, 60):
        clone = deepcopy(original)
        clone['measurement_id'] = 'SYNTHETIC long-property-' + str(i)
        delivery['measurements'].append(clone)
    for i in range(2):
        binding = deepcopy(spec['properties'][0])
        binding['property_id'] = 'SYNTHETIC other-property-' + str(i)
        spec['properties'].append(binding)
        clone = deepcopy(original)
        clone['measurement_id'] = 'SYNTHETIC other-result-' + str(i)
        clone['property_ref']['id'] = binding['property_id']
        delivery['measurements'].append(clone)
    units = build_units(delivery, spec, [], None, input_limit=10000)
    assert len(units) > 8
    assert {u['property_id'] for u in units[:3]} == {b['property_id'] for b in spec['properties']}
    assert {m['measurement_id'] for u in units for m in u['measurements']} == {m['measurement_id'] for m in delivery['measurements']}
    assert all(len(m['source_uncertainty']['components']) == 2 for u in units for m in u['measurements'])


def test_malformed_explanation_keeps_sealed_science_and_reports_partial(tmp_path):
    import asyncio
    from tests.rebuild.scenario import application, confirmed_case
    from tests.rebuild.test_knowledge_consumer import package

    async def run():
        app = application(tmp_path / 'data')
        package(app, tmp_path / 'kb')
        app.knowledge.import_release(tmp_path / 'kb')
        ordinary = app.models.json
        captured = []

        async def json_response(**kwargs):
            if kwargs['owner'] != 'M11':
                return await ordinary(**kwargs)
            import json
            prompt = json.loads(kwargs['messages'][0]['content'])
            captured.append(prompt)
            uid = prompt['units'][0]['unit_id']
            return {'units': [{'unit_id': uid, 'paragraphs': [{'text': 'SYNTHETIC invalid output',
                'kind': 'source_fact', 'measurement_ids': None, 'claim_ids': []}]}]}, {'attempt_id': 'SYNTHETIC model'}

        app.models.json = json_response
        with app.repository.transaction() as conn:
            conn.execute('INSERT INTO settings VALUES(?,?,1)', ('profile:M11', canonical({'state': 'validated', 'synthetic': True})))
        state, _ = await confirmed_case(app)
        assert state['lifecycle'] == 'completed' and state['science_state'] == 'sealed'
        with app.repository.read() as conn:
            body = app.delivery.get(conn, state['task_id'])
            report = app.repository.object(conn, state['task_id'], 'insight', state['insight_ref']['id'])
        assert captured and 'snapshot_ref' not in captured[0]
        with app.repository.read() as conn:
            bindings=app.repository.objects(conn,state['task_id'],'model_binding')
        assert any(b['bindings']['context'].get('snapshot_ref')==body['snapshot_ref'] for b in bindings)
        assert any(u['measurements'] and u['measurements'][0]['processed_value']['main_state'] == 'ready' for prompt in captured for u in prompt['units'])
        assert report['status'] == 'partial' and report['units'][0]['reason'] == 'INSIGHT_PARAGRAPH_SCHEMA'
        assert all(u['generation_mode'] == 'deterministic_basic' and u['status'] == 'basic' for u in report['units'])
        assert all('扩展解释未完成' in u['paragraphs'][0]['text'] for u in report['units'])
        assert body['measurements'][0]['raw_value'] == '0' and len(report['facts']) == 1
        assert not state['reviews'] and app.budget.summary()['committed_micros'] == 0

    asyncio.run(run())


def test_controlled_snapshot_numbers_allow_group_background_without_per_row_repetition():
    import pytest
    from astroquery_ai.science.insight_validation import validate_units, explanation_coverage
    from astroquery_ai.runtime.errors import DomainError
    delivery, _ = case()
    delivery['derived'][0]['coordinate_units'] = {'target': {'canonical_symbol': 'cm'}}
    row = measurement_input(delivery, delivery['measurements'][0])
    other = deepcopy(row); other['measurement_id'] = 'SYNTHETIC unmentioned'
    unit = {'unit_id': 'SYNTHETIC group', 'measurements': [row, other], 'claims': []}
    p = {'kind': 'source_fact', 'text': '该来源的原报为{{v0}}，处理后为{{v1}}。',
         'measurement_ids': [row['measurement_id']], 'claim_ids': [], 'value_assertions': [
             {'measurement_id': row['measurement_id'], 'coordinate': 'source'},
             {'measurement_id': row['measurement_id'], 'coordinate': 'processed'}]}
    response = {'units': [{'unit_id': unit['unit_id'], 'numeric_mode': 'snapshot_placeholders/1', 'paragraphs': [p]}]}
    result = validate_units(response, [unit])[0][1]
    assert result[0]['text'] == '该来源的原报为2 m，处理后为200 cm。'
    assert '{{v0}}' in result[0]['text_template']
    unit['paragraphs'] = result
    assert explanation_coverage(unit)['not_individually_discussed'] == ['SYNTHETIC unmentioned']
    assert 'value' not in p['value_assertions'][0]  # input remains unchanged
    forged = deepcopy(response)
    forged['units'][0]['paragraphs'][0]['value_assertions'][0]['value'] = '999'
    with pytest.raises(DomainError, match='快照'):
        validate_units(forged, [unit])
    forged = deepcopy(response)
    forged['units'][0]['paragraphs'][0]['text'] += '{{v7}}'
    with pytest.raises(DomainError, match='占位符'):
        validate_units(forged, [unit])
    forged = deepcopy(response)
    forged['units'][0]['paragraphs'][0]['text'] += '另一个结果为499.123。'
    with pytest.raises(DomainError, match='快照'):
        validate_units(forged, [unit])


def test_coherent_placeholder_offset_keeps_coordinates_and_log_basis():
    import pytest
    from astroquery_ai.science.insight_validation import validate_units
    from astroquery_ai.runtime.errors import DomainError
    delivery,_=case();row=measurement_input(delivery,delivery['measurements'][0])
    row['source_value']['representation']={'kind':'log10'}
    unit={'unit_id':'synthetic-log-unit','measurements':[row],'claims':[]}
    mid=row['measurement_id'];component=row['source_uncertainty']['components'][0]
    paragraphs=[{'kind':'source_fact','text':'坐标系数{{v0}}。','measurement_ids':[mid],'claim_ids':[],
        'value_assertions':[{'measurement_id':mid,'coordinate':'source'}]},
        {'kind':'source_fact','text':'单独误差{{v1}}。','measurement_ids':[mid],'claim_ids':[],
        'value_assertions':[{'measurement_id':mid,'coordinate':'source','component_id':component['component_id'],'value_key':'delta'}]}]
    response={'units':[{'unit_id':unit['unit_id'],'numeric_mode':'snapshot_placeholders/1','paragraphs':paragraphs}]}
    actual=validate_units(response,[unit])[0][1]
    assert actual[0]['text']=='坐标系数2（log10坐标，参考单位m）。'
    assert actual[1]['text']=='单独误差0.1 m。' and '{{v1}}' in actual[1]['original_text_template']
    forged=deepcopy(response);del forged['units'][0]['paragraphs'][1]['value_assertions'][0]['coordinate']
    with pytest.raises(DomainError,match='数值声明'):validate_units(forged,[unit])
