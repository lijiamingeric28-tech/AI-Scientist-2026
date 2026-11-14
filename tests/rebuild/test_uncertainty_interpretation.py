"""New synthetic source cases, exercised through the ordinary scheduler."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.scenario import application, confirmed_case, ScenarioModels, XML_HEADER


def setup_case(tmp_path, mode):
    app = application(tmp_path)
    calls = []
    raw_error = '0.2 stat; 0.4 sys' if mode == 'split' else '0.2'
    with app.repository.transaction() as conn:
        conn.execute("UPDATE settings SET payload=? WHERE key='profile:M08'", (
            canonical({'state': 'validated', 'synthetic': True, 'uncertainty_interpretation_enabled': True}),))

    class Models(ScenarioModels):
        async def json(self, *, owner, **kwargs):
            if owner == 'M08':
                calls.append(kwargs)
                data = loads(kwargs['messages'][-1]['content'])
                if mode == 'technical':
                    raise DomainError('PROVIDER_TIMEOUT', 'SYNTHETIC timeout')
                component = data['errors_to_interpret'][0]
                part = {'text': component['printed'], 'form': 'pm', 'numbers': ['0.2']}
                parts = [part]
                if mode == 'wrong_number':
                    part['numbers'] = ['0.9']
                if mode == 'invented_level':
                    part['level'] = {'kind': 'sigma_label', 'values': ['1'], 'text': '1 sigma'}
                if mode == 'invented_role':
                    part['role'] = 'sys'
                if mode == 'parsed_stat':
                    part['role'] = 'stat'
                if mode == 'split':
                    part.update(text='0.2 stat', role='stat')
                    parts.append({'text': '0.4 sys', 'form': 'pm', 'numbers': ['0.4'], 'role': 'sys'})
                if mode in {'pending_race', 'accepted_race'}:
                    with app.repository.transaction() as conn:
                        record = app.repository.objects(conn, kwargs['task_id'], 'measurement')[0]
                        question = app.reviews.register(conn, kwargs['task_id'], {
                            'origin': 'M03', 'owner': 'M03', 'issue_kind': 'uncertainty_semantics',
                            'issue_key': 'SYNTHETIC concurrent human question',
                            'question': 'SYNTHETIC existing question must remain under human authority',
                            'impact': 'Optional source error only',
                            'scope': {'measurement_ids': [record['measurement_id']]},
                            'basis': {'measurement_ref': {'id': record['measurement_id'],
                                'version': record['revision'], 'content_sha256': record['content_sha256']}},
                            'evidence_refs': record['evidence_refs'], 'allowed_actions': ['unable'],
                        })
                    if mode == 'accepted_race':
                        from astroquery_ai.runtime.reviews import ReviewAnswer
                        from uuid import uuid4
                        app.reviews.answer(ReviewAnswer(task_id=kwargs['task_id'], review_id=question['review_id'],
                            review_revision=question['revision'], basis_hash=question['basis_hash'],
                            client_request_id=str(uuid4()), action='unable',
                            reason='SYNTHETIC测试模拟审核；非用户本人作答，保留未解原报'))
                outcome = 'needs_review' if mode == 'needs_review' else 'unresolved' if mode == 'missing_evidence' else 'parsed'
                response = {'items': [{'id': component['id'], 'outcome': outcome,
                    'parts': parts if outcome == 'parsed' else [],
                    'evidence': [span['id'] for span in data['source_evidence']],
                    'reason': 'SYNTHETIC: explicit source interpretation, not independent science approval'}]}
                return response, {'attempt_id': 'SYNTHETIC error interpretation'}
            response, receipt = await super().json(owner=owner, **kwargs)
            if owner == 'M03':
                if 'id_column' in response:
                    response['properties'][0]['error_columns'] = ['e_Length']
                elif response.get('results'):
                    response['results'][0]['errors'] = [{
                        'location': 'e_Length', 'raw_text': raw_error, 'kind': 'other_reported',
                        'values': None, 'role': 'unspecified', 'meaning': 'reported_error',
                        'interpretation_state': 'unresolved', 'reason': 'SYNTHETIC reader left optional error unresolved'}]
            return response, receipt

    app.models = Models()

    def handle(request):
        if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu','vizier.idia.ac.za'} and request.url.path.endswith('/ReadMe'):
            return httpx.Response(404, text='SYNTHETIC: no ReadMe')
        if request.url.host == 'api.adsabs.harvard.edu':
            return httpx.Response(200, json={'response': {'numFound': 0, 'docs': []}})
        if request.url.host in {'vizier.cds.unistra.fr', 'vizier.cfa.harvard.edu', 'vizier.idia.ac.za'}:
            description = 'Statistical error' if mode == 'parsed_stat' else 'Source reported errors, separate stat/sys when labelled'
            header = XML_HEADER + f'<FIELD name="e_Length" datatype="char" arraysize="*" unit="m"><DESCRIPTION>{description}</DESCRIPTION></FIELD>'.encode()
            data = (f'<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0</TD><TD>{raw_error}</TD></TR></TABLEDATA></DATA>'.encode()
                    if 'Name' in request.url.params else b'')
            return httpx.Response(200, content=header + data + b'</TABLE></RESOURCE></VOTABLE>')
        raise AssertionError('No external network')

    app.http.transport = httpx.MockTransport(handle)
    return app, calls


@pytest.mark.parametrize('mode', ['parsed', 'parsed_stat', 'split', 'wrong_number', 'invented_level',
                                 'invented_role', 'technical', 'needs_review', 'missing_evidence', 'pending_race', 'accepted_race'])
def test_error_interpretation_routes_through_source_revision_quality_and_snapshot(tmp_path, mode):
    async def run():
        app, calls = setup_case(tmp_path, mode)
        state, _ = await confirmed_case(app)
        tid = state['task_id']
        assert len(calls) == 1
        with app.repository.read() as conn:
            records = app.repository.objects(conn, tid, 'measurement')
            record = records[0]
            receipts = app.repository.objects(conn, tid, 'uncertainty_interpretation_receipt')
            assert len(receipts) == 1
            receipt = receipts[0]
            assert receipt['human_answer_created'] is False and receipt['raw_source_replaced'] is False
            assert record['raw_value'] == '0' and record['value']['value'] == '0'
            answers = app.repository.objects(conn, tid, 'review_answer')
            assert len(answers) == (1 if mode == 'accepted_race' else 0)
            if mode in {'parsed', 'parsed_stat', 'split'}:
                assert record['revision'] == 2 and receipt['status'] == 'applied'
                original = app.repository.object(conn, tid, 'measurement', record['measurement_id'], 1)
                assert original['uncertainty']['components'][0]['interpretation_state'] == 'unresolved'
                assert original['content_sha256'] == receipt['input_hash']
                assert record['content_sha256'] == receipt['output_hash']
                components = record['uncertainty']['components']
                assert len(components) == (2 if mode == 'split' else 1)
                assert [c['values']['delta'] for c in components] == (['0.2', '0.4'] if mode == 'split' else ['0.2'])
                assert receipt['component_lineage'][0]['child_component_ids'] == [c['component_id'] for c in components]
                if mode == 'split':
                    assert [c['role'] for c in components] == ['stat', 'sys']
                    assert receipt['component_lineage'][0]['parent_component_id'] not in [c['component_id'] for c in components]
            else:
                assert record['revision'] == 1 and record['uncertainty']['components'][0]['values'] is None
            if mode == 'pending_race':
                assert state['lifecycle'] == 'waiting_review' and len(state['reviews']) == 1
                assert state['reviews'][0]['status'] == 'pending'
            else:
                assert state['lifecycle'] == 'completed'
                if mode == 'accepted_race':
                    assert len(state['reviews']) == 1 and state['reviews'][0]['status'] == 'unable'
                    assert receipt['status'] == 'not_applied'
                else:
                    assert not state['reviews']
                snapshot = app.delivery.get(conn, tid)
                assert snapshot['provenance_bundle']['uncertainty_interpretations'] == receipts
                assert snapshot['measurements'][0]['content_sha256'] == record['content_sha256']
        assert app.budget.summary()['committed_micros'] == 0
    asyncio.run(run())


def test_unqualified_normalization_profile_does_not_grant_interpretation(tmp_path):
    app, _ = setup_case(tmp_path, 'parsed')
    from astroquery_ai.science.workflow.context import ScienceContext
    from astroquery_ai.science.workflow.quality_service import QualityService
    service = QualityService(ScienceContext(app))
    with app.repository.transaction() as conn:
        conn.execute("UPDATE settings SET payload=? WHERE key='profile:M08'", (
            canonical({'state': 'validated', 'synthetic': True}),))
        assert not service._error_capable(conn)


def test_interpretation_does_not_publish_a_numeric_policy(tmp_path):
    async def run():
        app, calls = setup_case(tmp_path, 'parsed')
        load = app.registry.load
        def restricted(release_id=None):
            release = load(release_id)
            release['data']['conversion-policies'][0]['numeric_paths_state'] = 'not_published'
            return release
        app.registry.load = restricted
        state, _ = await confirmed_case(app)
        assert state['lifecycle'] == 'completed' and len(calls) == 1
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, state['task_id'])
            assert delivery['measurements'][0]['revision'] == 2
            assert delivery['measurements'][0]['uncertainty']['components'][0]['values'] == {'delta': '0.2'}
            assert delivery['derived'][0]['status'] == 'not_run'
            assert delivery['derived'][0]['interpretation_receipt_ref']
            history = delivery['provenance_bundle']['source_measurement_history']
            assert [record['revision'] for record in history] == [1, 2]
            assert history[0]['uncertainty']['components'][0]['values'] is None
    asyncio.run(run())


def test_unexpected_commit_failure_rolls_back_and_main_still_finishes(tmp_path, monkeypatch):
    from astroquery_ai.science.workflow.context import ScienceContext
    from astroquery_ai.runtime.scheduler import Scheduler
    original = ScienceContext.store_admitted
    dispatch = Scheduler.dispatch
    async def worker_dispatch(self, job):
        try:
            await dispatch(self, job)
        except Exception as exc:
            # scenario.run_until_wait deliberately uses direct dispatch;
            # this fault-injection case exercises the real worker failure path.
            self.fail(job, exc)
            await self.pipeline.advance(job['task_id'])
    monkeypatch.setattr(Scheduler, 'dispatch', worker_dispatch)
    def interrupted(self, conn, tid, result):
        original(self, conn, tid, result)
        if result['measurement']['revision'] == 2:
            raise RuntimeError('SYNTHETIC interrupted during error revision transaction')
    monkeypatch.setattr(ScienceContext, 'store_admitted', interrupted)
    async def run():
        app, calls = setup_case(tmp_path, 'parsed')
        state, _ = await confirmed_case(app)
        assert state['lifecycle'] == 'completed'
        assert len(calls) == 1  # durable successful model step; commit retries don't pay again
        with app.repository.read() as conn:
            tid = state['task_id']
            measurement = app.repository.objects(conn, tid, 'measurement')[0]
            assert measurement['revision'] == 1
            receipts = app.repository.objects(conn, tid, 'uncertainty_interpretation_receipt')
            assert len(receipts) == 1 and receipts[0]['status'] == 'not_checked'
            assert not state['reviews']
            assert len(app.delivery.get(conn, tid)['derived']) == 1
    asyncio.run(run())


def test_malformed_component_does_not_discard_an_independent_valid_component():
    from tests.support.uncertainty_cases import cases
    from astroquery_ai.science.uncertainty_interpretation import validate_proposal
    case = cases()[0]
    record, interpretation = deepcopy(case['source']), deepcopy(case['interpretation'])
    other = deepcopy(record['uncertainty']['components'][0])
    other['component_id'] = 'SYNTHETIC malformed second component'
    record['uncertainty']['components'].append(other)
    interpretation['proposal']['errors'].append(deepcopy(interpretation['proposal']['errors'][0]))
    error = deepcopy(interpretation['proposal']['errors'][0])
    error.update(kind='symmetric_delta', values={'delta': '0.34'}, interpretation_state='parsed',
                 role='stat', reason=None)
    raw = {'measurement_id': record['measurement_id'], 'input_hash': record['content_sha256'], 'components': [
        {'source_component_id': record['uncertainty']['components'][0]['component_id'], 'outcome': 'parsed',
         'errors': [error], 'reason': 'SYNTHETIC known source error', 'evidence_span_ids': [s['span_id'] for s in case['spans']]},
        {'source_component_id': other['component_id'], 'outcome': 'parsed', 'errors': [{}],
         'reason': 'SYNTHETIC invalid local schema', 'evidence_span_ids': []}]}
    proposal, outcomes, _ = validate_proposal(raw, record, interpretation, case['spans'])
    assert proposal.errors[0].values == {'delta': '0.34'}
    assert proposal.errors[1].interpretation_state == 'unresolved'
    assert outcomes[1]['reason'] == 'component_response_schema'


def test_parenthetical_digits_cannot_be_delivered_as_their_raw_integer():
    from tests.support.uncertainty_cases import cases
    from astroquery_ai.science.uncertainty_interpretation import validate_proposal
    case = cases()[2]
    error = deepcopy(case['interpretation']['proposal']['errors'][0])
    error.update(kind='symmetric_delta', values={'delta': '7'}, raw_text='7',
                 interpretation_state='parsed', reason=None)
    raw = {'measurement_id': case['source']['measurement_id'], 'input_hash': case['source']['content_sha256'],
        'components': [{'source_component_id': case['source']['uncertainty']['components'][0]['component_id'],
            'outcome': 'parsed', 'errors': [error], 'evidence_span_ids': [s['span_id'] for s in case['spans']],
            'reason': 'SYNTHETIC deliberately wrong parenthetical magnitude'}]}
    proposal, outcomes, _ = validate_proposal(raw, case['source'], case['interpretation'], case['spans'])
    assert proposal.errors[0].interpretation_state == 'unresolved'
    assert outcomes[0]['validation_reason'] == 'component_numbers_location_or_kind_not_supported'


def test_model_semantic_evidence_does_not_require_fixed_english_role_words():
    from tests.support.uncertainty_cases import cases
    from astroquery_ai.science.uncertainty_interpretation import validate_proposal
    case = cases()[0]
    record, interpretation = deepcopy(case['source']), deepcopy(case['interpretation'])
    spans = deepcopy(case['spans'])
    spans.append({'span_id': 'SYNTHETIC French role note', 'origin': 'checked_source_note', 'page': 1,
        'locator': 'SYNTHETIC note', 'text': 'SYNTHETIC: la fluctuation aléatoire de la mesure est indiquée par ce nombre.'})
    error = deepcopy(interpretation['proposal']['errors'][0])
    error.update(kind='symmetric_delta', values={'delta': '0.34'}, interpretation_state='parsed',
        role='stat', meaning='reported_error', reason=None, source_unit=None,
        semantic_support={'role': ['SYNTHETIC French role note']})
    raw = {'measurement_id': record['measurement_id'], 'input_hash': record['content_sha256'], 'components': [
        {'source_component_id': record['uncertainty']['components'][0]['component_id'], 'outcome': 'parsed',
         'errors': [error], 'reason': 'SYNTHETIC model assigns random measurement scatter to this component',
         'evidence_span_ids': [s['span_id'] for s in spans]}]}
    proposal, outcomes, _ = validate_proposal(raw, record, interpretation, spans)
    assert proposal.errors[0].role == 'stat'
    assert proposal.errors[0].values == {'delta': '0.34'}
    assert not outcomes[0]['semantic_basis']['literal_keyword_required']
    # A bare claim or foreign span ID still cannot supply this interpretation.
    raw['components'][0]['errors'][0]['semantic_support']['role'] = ['SYNTHETIC invented span']
    proposal, outcomes, _ = validate_proposal(raw, record, interpretation, spans)
    assert proposal.errors[0].interpretation_state == 'unresolved'
    assert outcomes[0]['validation_reason'] == 'semantic_support_not_bound_to_component_evidence'
