import asyncio
from copy import deepcopy

import httpx
import pytest

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.uncertainty_interpretation import prompt, validate_response, available_spans
from astroquery_ai.science.uncertainty_wire import propose_with_one_repair
from tests.support.uncertainty_cases import cases


def response(case, *, parts=None, evidence=None):
    return {'items': [{'id': 'u1', 'outcome': 'parsed',
        'parts': parts or [{'text': case['source']['uncertainty']['components'][0]['raw_text'],
                            'form': 'pm', 'numbers': ['0.34'], 'role': 'stat'}],
        'evidence': evidence or ['s2', 's4'], 'reason': 'SYNTHETIC source interpretation'}]}


def test_only_definition_cited_still_binds_owned_parenthetical_literal():
    case = cases()[2]
    raw = response(case, parts=[{'text': '2.531(7)', 'form': 'pm', 'numbers': ['0.007']}], evidence=['s4'])
    proposal, checks, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].values == {'delta': '0.007'}
    assert checks[0]['server_bound_original_span_ids'] and checks[0]['model_evidence_span_ids']
    assert proposal.errors[0].raw_text == '2.531(7)'


def test_scalar_transcription_restores_source_without_adding_model_labels():
    case = cases()[0]
    raw = response(case, parts=[{'text': '0.34 stat', 'form': 'pm', 'numbers': ['0.34'], 'role': 'stat'}])
    proposal, checks, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].interpretation_state == 'parsed'
    assert proposal.errors[0].raw_text == '0.34' and proposal.errors[0].role == 'stat'
    assert checks[0]['transcription_restored'][0]['proposed'] == '0.34 stat'
    raw['items'][0]['parts'][0]['numbers'] = ['0.35']
    proposal, _, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].interpretation_state == 'unresolved'


def test_explicit_component_selection_can_complete_a_parsed_amplitude_role():
    case = cases()[0]
    component = case['source']['uncertainty']['components'][0]
    component['interpretation_state'] = 'parsed'
    component['kind'] = 'symmetric_delta'
    component['values'] = {'delta': '0.34'}
    component['role'] = 'unspecified'
    cid = component['component_id']
    payload = prompt(case['source'], case['interpretation'], case['spans'], component_ids=[cid])
    assert len(payload['errors_to_interpret']) == 1
    proposal, checks, _ = validate_response(response(case), case['source'], case['interpretation'], case['spans'], component_ids=[cid])
    assert proposal.errors[0].role == 'stat' and proposal.errors[0].values == {'delta': '0.34'}
    assert checks[0]['outcome'] == 'parsed'


def test_one_sigma_is_removed_without_discarding_literal_error():
    case = cases()[0]
    raw = response(case)
    raw['items'][0]['parts'][0]['meaning'] = 'standard_uncertainty'
    proposal, checks, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].values == {'delta': '0.34'}
    assert proposal.errors[0].meaning == 'reported_error' and proposal.errors[0].level_kind is None
    assert checks[0]['discarded_unsubstantiated_labels'][0]['proposed'] == 'standard_uncertainty'


def test_completing_labels_cannot_turn_a_parsed_one_sided_error_into_pm():
    case = cases()[0]
    component = case['source']['uncertainty']['components'][0]
    component.update(interpretation_state='parsed', kind='asymmetric_delta', values={'minus': '0.34', 'plus': None})
    case['interpretation']['proposal']['errors'][0].update(interpretation_state='parsed', kind='asymmetric_delta', values={'minus': '0.34', 'plus': None})
    proposal, checks, _ = validate_response(response(case), case['source'], case['interpretation'], case['spans'], component_ids=[component['component_id']])
    assert proposal.errors[0].kind == 'asymmetric_delta' and proposal.errors[0].values == {'minus': '0.34', 'plus': None}
    assert checks[0]['validation_reason'] == 'one_sided_uncertainty_cannot_become_symmetric'


def test_existing_level_spelling_can_request_local_citation_repair_but_invention_cannot():
    from astroquery_ai.science.uncertainty_wire import format_repair_payload
    case = cases()[0]
    spans = [*case['spans'], {'span_id': 'synthetic-level', 'locator': 'table note',
        'text': 'SYNTHETIC all errors are at the 1{sigma} level.', 'origin': 'original_table_note'}]
    raw = response(case, parts=[{'text': '0.34', 'form': 'pm', 'numbers': ['0.34'],
        'level': {'kind': 'sigma_label', 'values': ['1'], 'text': '1 sigma'}}])
    payload = prompt(case['source'], case['interpretation'], spans)
    assert format_repair_payload(raw, case['source'], case['interpretation'], spans, payload)['format_feedback']['retry_only_ids'] == ['u1']
    raw['items'][0]['parts'][0]['level'] = {'kind': 'sigma_label', 'values': ['7'], 'text': '7 sigma'}
    assert format_repair_payload(raw, case['source'], case['interpretation'], spans, payload) is None


def test_known_stat_sys_parent_cannot_lose_a_reported_component():
    case = cases()[3]
    raw = response(case, parts=[{'text': '0.12 stat', 'form': 'pm', 'numbers': ['0.12'], 'role': 'stat'}])
    proposal, checks, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].interpretation_state == 'unresolved'
    assert checks[0]['validation_reason'] == 'reported_component_role_lost'


def test_global_wrong_alias_cannot_change_a_measurement():
    case = cases()[0]
    raw = response(case)
    raw['items'][0]['id'] = 'u99'
    with pytest.raises(DomainError, match='响应须保留所有请求误差身份'):
        validate_response(raw, case['source'], case['interpretation'], case['spans'])


@pytest.mark.parametrize('repair_changes_good_sibling', [False, True])
def test_one_format_repair_is_local_and_retains_valid_siblings(repair_changes_good_sibling):
    async def run():
        case = deepcopy(cases()[0])
        second = deepcopy(case['source']['uncertainty']['components'][0])
        second.update(component_id='SYNTHETIC second source error', raw_text='0.14')
        case['source']['uncertainty']['components'].append(second)
        error = deepcopy(case['interpretation']['proposal']['errors'][0])
        error.update(location='e_Second', raw_text='0.14')
        case['interpretation']['proposal']['errors'].append(error)
        evidence = deepcopy(case['source_evidence'])
        doc = loads(evidence['raw_text'])
        doc['cells']['e_Second'] = '0.14'
        doc['columns'].append({'name': 'e_Second', 'unit_text': 'm', 'description': 'Systematic uncertainty'})
        from astroquery_ai.runtime.codec import canonical
        evidence['raw_text'] = canonical(doc).decode()
        case['spans'] = available_spans(evidence, case['interpretation'])
        first = response(case)
        first['items'].append({'id': 'u2', 'outcome': 'parsed', 'parts': [None], 'evidence': ['s3', 's6']})
        calls = []
        async def invoke(messages):
            payload = loads(messages[-1]['content'])
            calls.append(payload)
            if len(calls) == 1:
                return first, {'attempt_id': 'SYNTHETIC first'}
            assert [i['id'] for i in payload['errors_to_interpret']] == ['u2']
            items = [{'id': 'u2', 'outcome': 'parsed', 'parts': [
                {'text': '0.14', 'form': 'pm', 'numbers': ['0.14'], 'role': 'sys'}], 'evidence': ['s3', 's6']}]
            if repair_changes_good_sibling:
                items.append({'id': 'u1', 'outcome': 'parsed', 'parts': [{'text': '999', 'form': 'pm', 'numbers': ['999']}], 'evidence': ['s2']})
            return {'items': items}, {'attempt_id': 'SYNTHETIC repair'}
        trace = []
        result, _ = await propose_with_one_repair(invoke, case['source'], case['interpretation'], case['spans'],
            prompt(case['source'], case['interpretation'], case['spans']), trace)
        assert len(calls) == 2 and trace[-1]['requested_ids'] == ['u2']
        proposal, _, _ = validate_response(result, case['source'], case['interpretation'], case['spans'])
        assert proposal.errors[0].values == {'delta': '0.34'}
        assert proposal.errors[1].interpretation_state == ('unresolved' if repair_changes_good_sibling else 'parsed')
    asyncio.run(run())


def test_transport_retry_is_bounded_and_unknown_science_is_not_retried():
    async def run():
        case = cases()[0]
        calls = []
        async def invoke(messages):
            calls.append(messages)
            if len(calls) == 1:
                raise httpx.ConnectError('SYNTHETIC transport interruption')
            return response(case), {'attempt_id': 'SYNTHETIC second'}
        trace = []
        await propose_with_one_repair(invoke, case['source'], case['interpretation'], case['spans'],
            prompt(case['source'], case['interpretation'], case['spans']), trace)
        assert len(calls) == 2 and trace[-1]['kind'] == 'bounded_transport_retry'
        calls.clear()
        async def unresolved(messages):
            calls.append(messages)
            return {'items': [{'id': 'u1', 'outcome': 'unresolved', 'parts': [], 'evidence': ['s2'],
                               'reason': 'SYNTHETIC missing source definition'}]}, {'attempt_id': 'SYNTHETIC one'}
        await propose_with_one_repair(unresolved, case['source'], case['interpretation'], case['spans'],
            prompt(case['source'], case['interpretation'], case['spans']), [])
        assert len(calls) == 1
    asyncio.run(run())


def test_large_catalog_keeps_exact_local_group_and_original_table_notes():
    case = cases()[0]
    evidence = deepcopy(case['source_evidence'])
    doc = loads(evidence['raw_text'])
    for index in range(500):
        name = f'Unrelated{index}'
        doc['cells'][name] = str(index)
        doc['columns'].append({'name': name, 'unit_text': 'm', 'description': 'Unrelated quantity ' * 80})
    from astroquery_ai.runtime.codec import canonical
    evidence['raw_text'] = canonical(doc).decode()
    spans = available_spans(evidence, case['interpretation'], {'metadata': {'description': 'All errors are source reported.'}})
    assert len(spans) == 5 and not any('Unrelated' in s['text'] for s in spans)
    assert any(s['origin'] == 'original_table_note' for s in spans)
    assert len(canonical(prompt(case['source'], case['interpretation'], spans))) < 16000


@pytest.mark.parametrize('definition,form,numbers,meaning', [
    ('Variance of Length; not a standard deviation', 'variance', ['0.0625'], 'standard_uncertainty'),
    ('Interval bounds; confidence level is not stated', 'bounds', ['1.1', '1.9'], 'confidence_interval'),
])
def test_negated_scientific_label_is_not_promoted(definition, form, numbers, meaning):
    raw_text = '0.0625' if form == 'variance' else '[1.1,1.9]'
    case = cases(definitions_override=[('SYNTHETIC negated label', '1.5', raw_text, definition,
        [('variance' if form == 'variance' else 'interval_endpoints', {}, 'unspecified', None)])],
        error_units={'SYNTHETIC negated label': 'm2' if form == 'variance' else 'm'})[0]
    raw = response(case, parts=[{'text': raw_text, 'form': form, 'numbers': numbers, 'meaning': meaning}])
    proposed, checks, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposed.errors[0].interpretation_state == 'parsed'
    assert proposed.errors[0].meaning == 'reported_error'
    assert checks[0]['discarded_unsubstantiated_labels'][0]['proposed'] == meaning


def test_unknown_level_does_not_erase_an_explicit_statistical_role():
    case = cases(definitions_override=[('SYNTHETIC known role unknown level', '1.5', '0.034',
        'Statistical uncertainty with unspecified confidence level',
        [('symmetric_delta', {'delta': '0.034'}, 'stat', None)])])[0]
    raw = response(case, parts=[{'text': '0.034', 'form': 'pm', 'numbers': ['0.034'], 'role': 'stat'}])
    proposed, _, _ = validate_response(raw, case['source'], case['interpretation'], case['spans'])
    assert proposed.errors[0].interpretation_state == 'parsed' and proposed.errors[0].role == 'stat'
    assert proposed.errors[0].level_kind is None
