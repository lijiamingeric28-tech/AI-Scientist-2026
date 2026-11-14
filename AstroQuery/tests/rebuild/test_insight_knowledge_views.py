"""Task-scoped knowledge reads never replace saved evidence with current KB."""
from copy import deepcopy

from fastapi.testclient import TestClient

from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.science.material_summaries import _identity
from tests.rebuild.test_delivery_projection_index import application


def seed(repo, tid, body):
    spec = {'properties': deepcopy(body['definitions']), 'run_policy': {},
            'knowledge_release': {'id': 'saved-release', 'version': 1, 'content_sha256': 'k'}}
    with repo.transaction() as c:
        ref = repo.put_object(c, tid, 'confirmed_query', 'query', 1, spec)
        c.execute('UPDATE tasks SET query_ref=? WHERE task_id=?', (canonical(ref).decode(), tid))
    return spec


def summary(repo, tid, body, *, text='Saved background', version=1, snapshot=None):
    pid = body['definitions'][0]['property_id']
    row = {'state': 'ready', 'material_id': 's1', 'property_id': pid,
           'snapshot_ref': snapshot or body['snapshot_ref'], 'text': 'Saved source introduction',
           'basis': {'property_id': pid, 'material_ids': ['s1'], 'evidence': [],
                     'knowledge': [{'entry_id': 'saved-knowledge', 'title': 'Task background',
                                    'claim': {'claim_id': 'saved-claim', 'text': text, 'role': 'definition'},
                                    'sources': [], 'conditions': [], 'authoring_basis': 'author_knowledge'}]}}
    with repo.transaction() as c:
        repo.put_object(c, tid, 'material_summary', _identity(body, 's1', pid), version, row)


def test_history_context_is_exact_saved_input_and_get_does_not_write(tmp_path):
    repo, _, tid, body, app = application(tmp_path)
    seed(repo, tid, body); summary(repo, tid, body)
    with repo.read() as c:
        before = c.execute('SELECT count(*) FROM objects').fetchone()[0]
    with TestClient(app) as client:
        response = client.get(f'/api/tasks/{tid}/deliveries/delivery/knowledge_context?delivery_revision=1')
    assert response.status_code == 200
    data = response.json()
    assert data['origin'] == 'historical_saved_basis'
    assert data['snapshot_ref'] == body['snapshot_ref']
    context = data['context']
    assert context['content_sha256'] == content_hash(context)
    entry, = context['entries']
    assert entry['claim']['text'] == 'Saved background'
    assert entry['content_sha256'] == content_hash(entry)
    assert entry['property_ids'] == [body['definitions'][0]['property_id']]
    assert 'saved_input' in entry['usage']
    with repo.read() as c:
        assert c.execute('SELECT count(*) FROM objects').fetchone()[0] == before


def test_context_validates_version_before_returning_304(tmp_path):
    repo, _, tid, body, app = application(tmp_path)
    seed(repo, tid, body); summary(repo, tid, body)
    base = f'/api/tasks/{tid}/deliveries/delivery/knowledge_context?delivery_revision=1'
    with TestClient(app) as client:
        first = client.get(base)
        assert first.status_code == 200
        headers = {'If-None-Match': first.headers['etag']}
        assert client.get(base, headers=headers).status_code == 304
        changed = client.get(base + '&expected_delivery_revision=99', headers=headers)
        assert changed.status_code in {400, 409, 422}
        assert changed.json()['code'] == 'DELIVERY_CHANGED'


def test_history_ignores_summary_from_other_snapshot(tmp_path):
    repo, _, tid, body, app = application(tmp_path)
    seed(repo, tid, body); summary(repo, tid, body, snapshot={'id': 'other', 'version': 1, 'content_sha256': 'x'})
    with TestClient(app) as client:
        data = client.get(f'/api/tasks/{tid}/deliveries/delivery/knowledge_context').json()
    assert data['context']['entries'] == []
    assert data['context']['properties'][0]['state'] == 'missing'


def test_historical_cutoff_uses_latest_visible_summary_version(tmp_path):
    from astroquery_ai.application.insight_views import historical_knowledge_context
    repo, _, tid, body, _ = application(tmp_path)
    spec = seed(repo, tid, body)
    summary(repo, tid, body, text='First saved background')
    summary(repo, tid, body, text='Later saved background', version=2)
    with repo.transaction() as c:
        c.execute("UPDATE objects SET created_at='2020-01-01' WHERE kind='material_summary' AND version=1")
        c.execute("UPDATE objects SET created_at='2022-01-01' WHERE kind='material_summary' AND version=2")
    with repo.read() as c:
        old = historical_knowledge_context(repo, c, tid, body, spec, before='2021-01-01')
        current = historical_knowledge_context(repo, c, tid, body, spec)
    assert old['entries'][0]['claim']['text'] == 'First saved background'
    assert current['entries'][0]['claim']['text'] == 'Later saved background'
    assert old['content_sha256'] != current['content_sha256']


def test_new_context_tamper_rejected_before_conditional_response(tmp_path):
    from astroquery_ai.science.task_knowledge import KIND, MODE
    repo, _, tid, body, app = application(tmp_path)
    spec = seed(repo, tid, body)
    context = {'schema_version': 'TaskKnowledgeContext/1', 'context_id': 'task-context',
               'knowledge_release_ref': spec['knowledge_release'], 'entries': [], 'properties': [],
               'library_version': 1}
    context['content_sha256'] = content_hash(context)
    with repo.transaction() as c:
        ref = repo.put_object(c, tid, KIND, 'task-context', 1, context)
        spec.update(knowledge_context_ref=ref, run_policy={'insights': {'presentation': MODE}})
        qref = repo.put_object(c, tid, 'confirmed_query', 'query', 2, spec)
        c.execute('UPDATE tasks SET query_ref=? WHERE task_id=?', (canonical(qref).decode(), tid))
    url = f'/api/tasks/{tid}/deliveries/delivery/knowledge_context?delivery_revision=1'
    with TestClient(app) as client:
        first = client.get(url)
        assert first.status_code == 200
        context['library_version'] = 99
        with repo.transaction() as c:
            c.execute("UPDATE objects SET payload=? WHERE task_id=? AND kind=? AND object_id='task-context'",
                      (canonical(context), tid, KIND))
        changed = client.get(url, headers={'If-None-Match': first.headers['etag']})
        assert changed.status_code == 409
        assert changed.json()['code'] == 'TASK_KNOWLEDGE_HASH'


def test_new_policy_missing_context_never_falls_back_to_historical_basis(tmp_path):
    repo, _, tid, body, app = application(tmp_path)
    spec = seed(repo, tid, body)
    spec['run_policy'] = {'insights': {'presentation': 'research-workbench/2'}}
    with repo.transaction() as c:
        ref = repo.put_object(c, tid, 'confirmed_query', 'query', 2, spec)
        c.execute('UPDATE tasks SET query_ref=? WHERE task_id=?', (canonical(ref).decode(), tid))
    with TestClient(app) as client:
        response = client.get(f'/api/tasks/{tid}/deliveries/delivery/knowledge_context')
    assert response.status_code == 409
    assert response.json()['code'] == 'TASK_KNOWLEDGE_MISSING'


def test_bundle_material_counts_use_its_saved_child_report():
    from astroquery_ai.application.material_workbench import material_overview
    body = {'definitions': [{'property_id': 'p', 'definition': {'name_cn': 'Saved quantity'}}],
            'insight_report': {'schema_version': 'InsightBundle/1', 'status': 'partial',
                'material_report': {'schema_version': 'MaterialSummaryReport/1', 'status': 'generated',
                    'counts': {'p': {'requested': 3, 'ready': 3, 'failed': 0}}}}}
    overview = material_overview(body)
    assert overview is not None
    assert overview['state'] == 'generated'
    assert overview['properties'][0]['ready'] == 3


def test_new_bundle_presentation_enters_material_workspace_before_report(tmp_path):
    from uuid import uuid4
    from astroquery_ai.api.http import create_app
    from astroquery_ai.application.presentation import presentation
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC insight workspace', str(uuid4()))['task_id']
    with app.repository.transaction() as c:
        spec = {'properties': [], 'run_policy': {'insights': {'mode': 'dot_author/1',
                                                             'presentation': 'research-workbench/2'}}}
        ref = app.repository.put_object(c, tid, 'confirmed_query', 'query', 1, spec)
        app.repository.mutate_task(c, tid, query_ref=canonical(ref).decode())
        app.repository.event(c, tid, 'query_confirmed', {'spec_ref': ref})
    assert presentation(app, tid)['material_summary_mode'] is True
    stage = next(s for s in presentation(app, tid)['stages'] if s['id'] == 'insight')
    assert stage['name'] == '资料总结与性质洞察'


def test_bundle_insights_are_saved_only_and_reject_out_of_scope_cursor(tmp_path, monkeypatch):
    from astroquery_ai.science.theory_knowledge import TheoryKnowledgeStore
    repo, _, tid, body, app = application(tmp_path)
    report = {'schema_version': 'InsightBundle/1', 'report_id': 'saved-bundle',
              'delivery_id': 'delivery', 'snapshot_ref': body['snapshot_ref'], 'status': 'partial',
              'knowledge_context_ref': {'id': 'saved-context', 'version': 1},
              'material_report': {'schema_version': 'MaterialSummaryReport/1'},
              'property_report': {'schema_version': 'InsightReport/4', 'cards': [], 'knowledge_blocks': []}}
    with repo.transaction() as c:
        ref = repo.put_object(c, tid, 'insight', 'saved-bundle', 1, report)
        body.update(revision=2, insight={'report_ref': ref}, insight_report=report)
        ref = repo.put_object(c, tid, 'delivery', 'delivery', 2, body)
        c.execute('UPDATE tasks SET delivery_ref=? WHERE task_id=?', (canonical(ref).decode(), tid))
    calls = []
    def forbidden(*_):
        calls.append(1)
        raise AssertionError('Frozen Bundle must never enrich from the current theory store')
    monkeypatch.setattr(TheoryKnowledgeStore, 'get_instance', forbidden)
    url = f'/api/tasks/{tid}/deliveries/delivery/insights?delivery_revision=2'
    with TestClient(app) as client:
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['items'] == [report]
        assert calls == []
        assert client.get(url + '&at_seq=999999').status_code == 409


def test_escaped_insight_failure_finalizes_partial_bundle_without_changing_science(tmp_path):
    import asyncio
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY
    from astroquery_ai.runtime.codec import loads
    from tests.rebuild.scenario import application as scenario_app, confirmed_case, synthetic_author_manifest

    async def run():
        app = scenario_app(tmp_path / 'data')
        manifest = synthetic_author_manifest(app)
        app.knowledge.load = lambda *_: {'manifest': manifest, 'sources': {},
            'author': {'sources': [], 'entries': [], 'bindings': []}}
        ordinary = app.models.json
        async def model(**kwargs):
            if kwargs['profile'].version == 'unified-catalog-quality-2':
                body = loads(kwargs['messages'][-1]['content'])
                return {'items': [{'item_id': r['item_id'], 'subject': 'target', 'quantity_relation': 'same',
                    'reported_quantity': 'SYNTHETIC whole length', 'subject_scale': 'whole', 'result_role': 'reported_result',
                    'native_representation': 'linear', 'value_match': 'exact', 'unit_match': 'exact', 'errors_match': 'not_reported',
                    'evidence_columns': ['Length'], 'checked_ids': list(body['source_materials'])[:1],
                    'caution_ids': [], 'review_issue': None, 'reason': 'SYNTHETIC source'} for r in body['items']]}, {
                    'attempt_id': 'synthetic-quality'}
            return await ordinary(**kwargs)
        app.models.json = model
        def setup(scheduler):
            async def escaped(job):
                scheduler.fail(job, DomainError('SYNTHETIC_ESCAPED', 'Synthetic escaped handler failure'))
            scheduler.handlers['insights'] = escaped
        policy = deepcopy(NORMAL_RUN_POLICY)
        policy['insights'] = {'mode': 'dot_author/1', 'presentation': 'research-workbench/2'}
        state, _ = await confirmed_case(app, run_policy=policy, setup_scheduler=setup)
        assert state['lifecycle'] == 'completed'
        with app.repository.read() as c:
            final = app.delivery.get(c, state['task_id'])
            first = app.repository.object(c, state['task_id'], 'delivery', final['delivery_id'], 1)
            assert final['revision'] == 2
            assert final['insight_report']['schema_version'] == 'InsightBundle/1'
            assert final['insight_report']['status'] == 'partial'
            assert final['insight_report']['components']['material']['reason'] == 'SYNTHETIC_ESCAPED'
            assert final['measurements'] == first['measurements']
            assert final['snapshot_ref'] == first['snapshot_ref']
    asyncio.run(run())
