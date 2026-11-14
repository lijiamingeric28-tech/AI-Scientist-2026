import asyncio
from copy import deepcopy

import pytest

from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.scenario import application, confirmed_case


@pytest.fixture
def case(tmp_path, monkeypatch):
    app = application(tmp_path)
    state, _ = asyncio.run(confirmed_case(app))
    tid = state['task_id']
    with app.repository.read() as c:
        body = deepcopy(app.delivery.get(c, tid))
    app.profile_authority.authorize = lambda *args: {'synthetic': True, 'scope': 'controlled test only'}
    calls = []
    async def model(**kwargs):
        from astroquery_ai.science.property_insights import unpack_materials
        payload = unpack_materials(loads(kwargs['messages'][-1]['content']))
        calls.append(kwargs)
        row = payload['record_index'][0]
        entry = {'text': '来源记录保留原始测量，按实际条件分别参考。',
                 'measurement_ids': [row['measurement_id']], 'evidence_ids': row['evidence_ids'][:1], 'claim_ids': []}
        return {'found': [entry], 'comparison': [], 'uses': [], 'limitations': [], 'findings': [],
                'recommendations': {'benchmark': {**entry, 'reason': entry['text']}}}, {
                'attempt_id': 'SYNTHETIC-controlled', 'model': 'qwen3.8-max'}
    app.models.json = model
    source = body['measurements'][0]['source_ref']['id']
    pid = body['definitions'][0]['property_id']
    return app, tid, body, source, pid, calls


def test_supplement_requests_stay_within_installed_qualified_output_limit(case):
    app, tid, body, source, pid, calls = case
    profile = app.material_analysis.profile()
    assert profile.max_output_tokens == 4096
    assert profile.version == 'research-property-short-2'
    assert profile.model == 'qwen3.8-max'


def test_reads_never_generate_and_completed_task_remains_immutable(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    view = service.read(tid, body['delivery_id'], body['revision'], source, pid)
    assert view['versions'] == [] and view['report'] is None
    assert view['scope']['kind'] == 'material'
    assert calls == []
    with app.repository.read() as c:
        assert app.repository.task(c, tid)['lifecycle'] == 'completed'
        assert canonical(app.delivery.get(c, tid)) == canonical(body)


def test_duplicate_start_generates_once_and_publishes_only_supplement(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    request = {'operation_id': 'test-operation', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    first = service.submit(tid, body['delivery_id'], request)
    assert service.submit(tid, body['delivery_id'], request)['run_id'] == first['run_id']
    asyncio.run(service.execute(first['run_id']))
    result = service.read(tid, body['delivery_id'], body['revision'], source, pid)
    assert result['report']['schema_version'] == 'MaterialAnalysis/1'
    assert result['report']['status'] == 'complete'
    assert len(calls) == 1
    assert service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'second-click'})['run_id'] == first['run_id']
    assert result['report']['coverage']['completed_ids'] == result['report']['coverage']['requested_ids']
    with app.repository.read() as c:
        task = app.repository.task(c, tid)
        assert task['lifecycle'] == 'completed'
        assert canonical(app.delivery.get(c, tid)) == canonical(body)
        assert app.repository.objects(c, tid, 'material_analysis')


@pytest.mark.parametrize('method', ['saved_material_summary_reuse', 'saved_source_comparison', 'saved_batch_and_summary'])
def test_saved_reading_fallback_does_not_block_resuming_missing_model_work(case, method):
    """A readable local revision is useful, but is not a completed model run."""
    app, tid, body, source, pid, calls = case
    service = app.material_analysis
    request = {'operation_id': 'reading-fallback', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    first = service.submit(tid, body['delivery_id'], request)
    asyncio.run(service.execute(first['run_id']))
    with app.repository.transaction() as c:
        state = loads(c.execute('SELECT payload FROM material_analysis_runs WHERE run_id=?', (first['run_id'],)).fetchone()[0])
        ref = state['reports'][-1]
        report = app.repository.object(c, tid, 'material_analysis', ref['id'], ref['version'])
        report['generation_method'] = method
        fallback = app.repository.put_object(c, tid, 'material_analysis', ref['id'], ref['version'] + 1, report)
        fallback.update(status='complete', generated_at=report['generated_at'])
        state['reports'].append(fallback)
        for checkpoint in state['checkpoints'].values():
            checkpoint.update(status='failed', reason='MODEL_NOT_COMPLETED')
        service._update(c, first['run_id'], state, 'complete')
    resumed = service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'resume-missing-model'})
    assert resumed['run_id'] != first['run_id']
    asyncio.run(service.execute(resumed['run_id']))
    assert len(calls) == 2
    view = service.read(tid, body['delivery_id'], body['revision'], source, pid)
    assert view['report'].get('generation_method', 'model') == 'model'
    assert view['versions'][0]['version'] == fallback['version'] + 1
    assert fallback in view['versions']


def test_stop_and_restart_do_not_reopen_task_or_dispatch(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    request = {'operation_id': 'stop', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    run = service.submit(tid, body['delivery_id'], request)
    service.stop(tid, run['run_id'])
    asyncio.run(service.execute(run['run_id']))
    assert service.status(tid, run['run_id'])['status'] == 'cancelled'
    assert calls == []
    request['operation_id'] = 'retry'
    retried = service.submit(tid, body['delivery_id'], request)
    with app.repository.transaction() as c:
        c.execute("UPDATE material_analysis_runs SET status='running' WHERE run_id=?", (retried['run_id'],))
    restarted = MaterialAnalysisService(app)
    restarted.recover()
    assert restarted.status(tid, retried['run_id'])['status'] == 'interrupted'
    assert calls == []


def test_qualification_and_version_refusals_create_no_runs(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    request = {'operation_id': 'bad', 'expected_delivery_revision': 999,
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    with pytest.raises(DomainError, match='交付'):
        service.submit(tid, body['delivery_id'], request)
    def refused(*args):
        raise DomainError('PROFILE_NOT_VALIDATED', '本配置未验证', 409)
    app.profile_authority.authorize = refused
    request['expected_delivery_revision'] = body['revision']
    with pytest.raises(DomainError, match='未验证'):
        service.submit(tid, body['delivery_id'], request)
    assert service.read(tid, body['delivery_id'], body['revision'], source, pid)['generation']['allowed'] is False
    with app.repository.read() as c:
        assert c.execute('SELECT count(*) FROM material_analysis_runs').fetchone()[0] == 0
    assert calls == []


def test_completed_task_budget_only_accepts_exact_running_analysis_permit(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService, permit_matches
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    request = {'operation_id': 'budget', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    run = service.submit(tid, body['delivery_id'], request)
    attempts = []
    original = app.models.json
    async def budget_checked(**kwargs):
        args = dict(task_id=tid, owner='M11', model='qwen3.8-max', root_id=kwargs['root_id'],
            request={'messages': kwargs['messages']}, input_bound=10, output_bound=10,
            profile_state='validated', purpose='production', smoke=True, root_limit=1)
        with pytest.raises(DomainError):
            app.budget.reserve(**{**args, 'request': {'messages': []}})
        with pytest.raises(DomainError):
            app.budget.reserve(**{**args, 'profile_state': 'report_only', 'purpose': 'material_summary'})
        attempt = app.budget.reserve(**args)
        attempts.append(attempt)
        app.budget.dispatch(attempt['attempt_id'])
        return await original(**kwargs)
    app.models.json = budget_checked
    asyncio.run(service.execute(run['run_id']))
    assert len(attempts) == 1
    assert service.status(tid, run['run_id'])['status'] == 'complete'
    with app.repository.read() as c:
        task = app.repository.task(c, tid)
        assert not permit_matches(app.repository, c, task, 'M08', 'qwen3.8-max', calls[0]['root_id'])
        assert not permit_matches(app.repository, c, task, 'M11', 'qwen3.8-max', calls[0]['root_id'], messages=[])


def test_http_analysis_endpoints_are_explicit_and_versioned(case):
    from fastapi.testclient import TestClient
    from astroquery_ai.api.http import create_app
    app, tid, body, source, pid, calls = case
    http = create_app(app.root, application=app, start_worker=False)
    base = f'/api/tasks/{tid}/deliveries/{body["delivery_id"]}/material-analysis'
    query = {'delivery_revision': body['revision'], 'expected_delivery_revision': body['revision'],
             'material_id': source, 'property_id': pid, 'scope': 'material'}
    with TestClient(http) as client:
        result = client.get(base, params=query)
        assert result.status_code == 200
        assert result.json()['versions'] == [] and calls == []
        assert client.get(base, params={**query, 'scope': 'property_comparison'}).json()['scope']['kind'] == 'property_comparison'
        request = {'operation_id': 'http', 'expected_delivery_revision': body['revision'],
                   'material_id': source, 'property_id': pid, 'scope': 'material'}
        created = client.post(base, json=request)
        assert created.status_code == 202
        run_id = created.json()['run_id']
        path = f'/api/tasks/{tid}/material-analysis-runs/{run_id}'
        assert client.get(path).json()['status'] == 'queued'
        assert client.post(path+'/stop', json={}).json()['status'] == 'cancelled'
        assert client.get(base, params={**query, 'at_seq': 999999}).status_code == 409
        assert client.get(base, params={**query, 'expected_delivery_revision': 999}).status_code == 409
        assert calls == []


def test_followup_reads_selected_supplement_context_and_rejects_a_wrong_hash(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    from astroquery_ai.agent_harness.data_loader import load_task_bundle
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    app.material_analysis = service
    run = service.submit(tid, body['delivery_id'], {'operation_id': 'followup',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    asyncio.run(service.execute(run['run_id']))
    view = service.read(tid, body['delivery_id'], body['revision'], source, pid)
    ref = {key: view['versions'][0][key] for key in ('id', 'version', 'content_sha256')}
    bundle = load_task_bundle(tid, app, body['delivery_id'], body['revision'], material_analysis_ref=ref)
    assert bundle.material_analysis['input_hash'] == view['report']['input_hash']
    assert bundle.knowledge_context['content_sha256'] == view['report']['knowledge_context_sha256']
    with pytest.raises(DomainError):
        load_task_bundle(tid, app, body['delivery_id'], body['revision'], material_analysis_ref={**ref, 'content_sha256': 'foreign'})


def test_replay_cutoff_cannot_see_later_supplement_and_task_cursor_is_unchanged(case):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    before = app.repository.get_task(tid)['last_event_seq']
    run = service.submit(tid, body['delivery_id'], {'operation_id': 'history',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    asyncio.run(service.execute(run['run_id']))
    archived = service.read(tid, body['delivery_id'], body['revision'], source, pid, at_seq=before)
    assert archived['versions'] == [] and archived['report'] is None
    assert archived['generation']['allowed'] is False
    with pytest.raises(DomainError):
        service.status(tid, run['run_id'], at_seq=before)
    assert app.repository.get_task(tid)['last_event_seq'] == before


@pytest.mark.parametrize('target', ['delivery', 'run_context'])
def test_tampered_supplement_inputs_refuse_before_model_dispatch(case, target):
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app, tid, body, source, pid, calls = case
    service = MaterialAnalysisService(app)
    run = service.submit(tid, body['delivery_id'], {'operation_id': 'tamper',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    with app.repository.transaction() as c:
        if target == 'delivery':
            broken = deepcopy(body)
            broken['measurements'][0]['raw_value'] = 'TAMPERED'
            c.execute("UPDATE objects SET payload=? WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                (canonical(broken), tid, body['delivery_id'], body['revision']))
            app.delivery._display_key = None
        else:
            state = loads(c.execute('SELECT payload FROM material_analysis_runs WHERE run_id=?', (run['run_id'],)).fetchone()[0])
            state['context']['library_version'] = 'TAMPERED'
            c.execute('UPDATE material_analysis_runs SET payload=? WHERE run_id=?', (canonical(state), run['run_id']))
    asyncio.run(service.execute(run['run_id']))
    assert calls == []
    assert service.status(tid, run['run_id'])['status'] == 'failed'


def test_property_comparison_counts_groups_without_this_property(case, monkeypatch):
    app, tid, body, source, pid, calls = case
    original = app.delivery.read_workbench
    def workbench(*args, **kwargs):
        header, index, boundary = original(*args, **kwargs)
        index = deepcopy(index)
        index.groups['unrelated'] = {'by_property': {}}
        return header, index, boundary
    monkeypatch.setattr(app.delivery, 'read_workbench', workbench)
    result = app.material_analysis.read(tid, body['delivery_id'], body['revision'], source, pid, 'property_comparison')
    assert result['scope']['record_count'] == len(body['measurements'])
    assert not calls


def test_failed_synthesis_preserves_batches_and_retry_only_synthesizes(case, monkeypatch):
    from astroquery_ai.science import property_insight_generation as generator
    app, tid, body, source, pid, calls = case
    service, plan = app.material_analysis, generator.plan
    def split(*args):
        groups, _ = plan(*args)
        return groups + groups, True
    monkeypatch.setattr(generator, 'plan', split)
    original = service._explain
    failed = []
    async def fail_synthesis(*args):
        if args[-1] == 'synthesis' and not failed:
            failed.append(True)
            return {'status': 'failed', 'reason': 'TEST_PROVIDER_TIMEOUT', 'measurement_ids': []}
        return await original(*args)
    monkeypatch.setattr(service, '_explain', fail_synthesis)
    request = {'operation_id': 'synthesis', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'property_comparison'}
    first = service.submit(tid, body['delivery_id'], request)
    asyncio.run(service.execute(first['run_id']))
    assert service.status(tid, first['run_id'])['status'] == 'partial'
    report = service.read(tid, body['delivery_id'], body['revision'], source, pid, 'property_comparison')['report']
    assert 'TEST_PROVIDER_TIMEOUT' in report['failure_reasons']
    assert report['sections']['found'] == []
    assert report['saved_batch_analyses'][0]['sections']['found']
    before = len(calls)
    retry = service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'retry-synthesis'})
    assert retry['run_id'] != first['run_id']
    asyncio.run(service.execute(retry['run_id']))
    assert service.status(tid, retry['run_id'])['status'] == 'complete'
    assert len(calls) == before + 1


@pytest.mark.parametrize('same_context', [True, False])
def test_comparison_synthesis_reuses_saved_material_reading_only_in_the_same_frozen_context(case, monkeypatch, same_context):
    from astroquery_ai.science import property_insight_generation as generator
    app, tid, body, source, pid, calls = case
    service = app.material_analysis
    request = {'operation_id': 'material-before-comparison', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    first = service.submit(tid, body['delivery_id'], request)
    asyncio.run(service.execute(first['run_id']))
    if not same_context:
        with app.repository.transaction() as c:
            saved = service.read(tid, body['delivery_id'], body['revision'], source, pid)
            report = saved['report']
            report['knowledge_context_sha256'] = 'different-frozen-context'
            app.repository.put_object(c, tid, 'material_analysis', saved['versions'][0]['id'], saved['versions'][0]['version'] + 1, report)
    plan = generator.plan
    def split(*args):
        groups, _ = plan(*args)
        return groups + groups, True
    monkeypatch.setattr(generator, 'plan', split)
    before = len(calls)
    comparison = service.submit(tid, body['delivery_id'], {**request, 'scope': 'property_comparison', 'operation_id': 'compare-saved-readings'})
    asyncio.run(service.execute(comparison['run_id']))
    assert service.status(tid, comparison['run_id'])['status'] == 'complete'
    assert len(calls) - before == (1 if same_context else 2)


def test_complete_saved_json_fields_publish_with_the_original_attempt_identity(case):
    """Provider cutoff must not lose paid, complete fields or their receipt."""
    from astroquery_ai.science import property_insights as cards
    app, tid, body, source, pid, calls = case
    saved_attempts = []
    async def cutoff(**kwargs):
        payload = cards.unpack_materials(loads(kwargs['messages'][-1]['content']))
        row = payload['record_index'][0]
        attempt = app.budget.reserve(task_id=tid, owner='M11', model='qwen3.8-max', root_id=kwargs['root_id'],
            request={'messages': kwargs['messages']}, input_bound=10, output_bound=10,
            profile_state='validated', purpose='production', smoke=True, root_limit=1)
        saved_attempts.append(attempt['attempt_id'])
        raw = canonical({'found': [{'text': '完整保存的原文观察。', 'measurement_ids': [row['measurement_id']],
            'evidence_ids': row['evidence_ids'][:1], 'claim_ids': []}]}).decode()[:-1] + ',"uses":[{"text":"unfinished'
        with app.repository.transaction() as c:
            app.repository.put_object(c, tid, 'model_response_diagnostic', attempt['attempt_id'], 1, {'raw_response': raw})
            c.execute('UPDATE attempts SET receipt=? WHERE attempt_id=?', (canonical({'model': 'qwen3.8-max', 'done': False}), attempt['attempt_id']))
        raise DomainError('INCOMPLETE_MODEL_RESPONSE', 'stream cutoff')
    app.models.json = cutoff
    run = app.material_analysis.submit(tid, body['delivery_id'], {'operation_id': 'saved-response',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    asyncio.run(app.material_analysis.execute(run['run_id']))
    report = app.material_analysis.read(tid, body['delivery_id'], body['revision'], source, pid)['report']
    assert report['status'] == 'complete'
    assert report['sections']['found'][0]['text'] == '完整保存的原文观察。'
    assert report['receipts'][0]['attempt_id'] == saved_attempts[0]


def test_successful_synthesis_survives_publication_failure_without_another_model_call(case, monkeypatch):
    from astroquery_ai.science import property_insight_generation as generator
    app, tid, body, source, pid, calls = case
    service, original_plan, original_publish = app.material_analysis, generator.plan, app.material_analysis._publish
    def split(*args):
        groups, _ = original_plan(*args)
        return groups + groups, True
    monkeypatch.setattr(generator, 'plan', split)
    failed = []
    async def publish(*args):
        if not failed:
            failed.append(True)
            raise OSError('controlled publication failure')
        return await original_publish(*args)
    monkeypatch.setattr(service, '_publish', publish)
    request = {'operation_id': 'publication-failure', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'property_comparison'}
    first = service.submit(tid, body['delivery_id'], request)
    asyncio.run(service.execute(first['run_id']))
    before = len(calls)
    assert service.status(tid, first['run_id'])['status'] == 'failed'
    second = service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'publish-saved-synthesis'})
    asyncio.run(service.execute(second['run_id']))
    assert service.status(tid, second['run_id'])['status'] == 'complete'
    assert len(calls) == before


def test_published_sample_preserves_supplements_without_private_run_state(case, tmp_path):
    import lzma
    import json
    from astroquery_ai.tools.pack_demos import build
    app, tid, body, source, pid, calls = case
    run = app.material_analysis.submit(tid, body['delivery_id'], {'operation_id': 'public',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    asyncio.run(app.material_analysis.execute(run['run_id']))
    sample = {'task_id': tid, 'delivery_id': body['delivery_id'], 'delivery_revision': body['revision'], 'snapshot_ref': body['snapshot_ref']}
    packed = tmp_path/'packed'
    packed.mkdir()
    with app.repository.read() as c:
        entry = build(c, sample, packed, {}, app.root/'artifacts')
    rows = [json.loads(line) for line in lzma.decompress((packed/(tid+'.jsonl.xz')).read_bytes()).splitlines()]
    public_runs = [row for table, row in rows if table == 'material_analysis_runs']
    assert len(public_runs) == 1
    public_state = json.loads(public_runs[0]['payload'])
    assert public_state['reports']
    assert not {'checkpoints', 'context', 'spec_ref'}.intersection(public_state)
    assert any(table == 'objects' and row['kind'] == 'material_analysis' for table, row in rows)
    assert not any(table == 'material_analysis_operations' or table == 'objects' and row['kind'] == 'material_analysis_permit' for table, row in rows)
    reader = application(tmp_path/'reader')
    reader.profile_authority.authorize = lambda *args: {'synthetic': True}
    from astroquery_ai.runtime.published_demos import PublishedDemos
    demos = PublishedDemos(reader)
    demos.directory, demos.index = packed, {tid: entry}
    assert demos.open(tid)
    view = reader.material_analysis.read(tid, body['delivery_id'], body['revision'], source, pid)
    assert view['report']['status'] == 'complete'
    assert len(view['versions']) == 1
    assert view['generation']['allowed'] is False
    with pytest.raises(DomainError):
        reader.material_analysis.submit(tid, body['delivery_id'], {'operation_id': 'forbidden',
            'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    # A public package must never smuggle queued model execution into a reader.
    import hashlib
    public_runs[0]['status'] = 'queued'
    archive = packed/(tid+'.jsonl.xz')
    archive.write_bytes(lzma.compress(b''.join(json.dumps(row).encode()+b'\n' for row in rows)))
    unsafe = {**entry, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    rejected = application(tmp_path/'rejected')
    rejected_demos = PublishedDemos(rejected)
    rejected_demos.directory, rejected_demos.index = packed, {tid: unsafe}
    with pytest.raises(DomainError): rejected_demos.open(tid)
    with rejected.repository.read() as c:
        assert c.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_whole_property_comparison_is_shared_across_current_materials(case, monkeypatch):
    app, tid, body, source, pid, calls = case
    service = app.material_analysis
    first = service.submit(tid, body['delivery_id'], {'operation_id': 'whole-property',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'property_comparison'})
    asyncio.run(service.execute(first['run_id']))
    original = app.delivery.read_workbench
    class AnotherMaterial:
        def __init__(self, index): self.index = index
        def __getattr__(self, key): return getattr(self.index, key)
        def resolve(self, mid, property_id):
            group, chosen = self.index.resolve(source if mid == 'another-current-material' else mid, property_id)
            return ({**group, 'group_id': mid} if mid == 'another-current-material' else group), chosen
    def workbench(*args, **kwargs):
        header, index, boundary = original(*args, **kwargs)
        return header, AnotherMaterial(index), boundary
    monkeypatch.setattr(app.delivery, 'read_workbench', workbench)
    view = service.read(tid, body['delivery_id'], body['revision'], 'another-current-material', pid, 'property_comparison')
    assert view['report'] and view['report']['status'] == 'complete'
    assert view['scope']['material_id'] == 'another-current-material'
    same = service.submit(tid, body['delivery_id'], {'operation_id': 'another-current-material',
        'expected_delivery_revision': body['revision'], 'material_id': 'another-current-material', 'property_id': pid, 'scope': 'property_comparison'})
    assert same['run_id'] == first['run_id']
    assert len(calls) == 1


def test_explicit_maintainer_update_is_limited_to_installed_sample_snapshot(case, monkeypatch):
    from astroquery_ai.runtime.published_demos import PublishedDemos
    app, tid, body, source, pid, calls = case
    with app.repository.transaction() as c:
        app.repository.put_object(c, tid, 'task_origin', tid, 1, {'source': 'sample'})
    monkeypatch.setattr(PublishedDemos, 'index', {tid: {'snapshot_ref': body['snapshot_ref']}})
    request = {'operation_id': 'maintainer', 'expected_delivery_revision': body['revision'],
               'material_id': source, 'property_id': pid, 'scope': 'material'}
    with pytest.raises(DomainError): app.material_analysis.submit(tid, body['delivery_id'], request)
    run = app.material_analysis.submit(tid, body['delivery_id'], request, sample_update=True)
    asyncio.run(app.material_analysis.execute(run['run_id']))
    assert app.material_analysis.status(tid, run['run_id'])['status'] == 'complete'
    assert not app.material_analysis.read(tid, body['delivery_id'], body['revision'], source, pid)['generation']['allowed']
    monkeypatch.setattr(PublishedDemos, 'index', {tid: {'snapshot_ref': {'id': 'other'}}})
    with pytest.raises(DomainError):
        app.material_analysis.submit(tid, body['delivery_id'], {**request, 'operation_id': 'wrong-snapshot'}, sample_update=True)


def test_sample_refresh_keeps_original_archive_rows_and_media_recipes(case, tmp_path):
    import json, lzma
    from astroquery_ai.tools.pack_demos import build, append_supplements
    app, tid, body, source, pid, calls = case
    sample = {'task_id': tid, 'delivery_id': body['delivery_id'], 'delivery_revision': body['revision'], 'snapshot_ref': body['snapshot_ref']}
    old, new = tmp_path/'old-pack', tmp_path/'new-pack'
    old.mkdir();new.mkdir()
    with app.repository.read() as c: entry = build(c, sample, old, {}, app.root/'artifacts')
    entry['media']['frozen-figure'] = {'parent': 'frozen-pdf', 'operation': 'figure_crop', 'options': {'page': 2}}
    original = lzma.decompress((old/(tid+'.jsonl.xz')).read_bytes()).splitlines()
    run = app.material_analysis.submit(tid, body['delivery_id'], {'operation_id': 'refresh',
        'expected_delivery_revision': body['revision'], 'material_id': source, 'property_id': pid, 'scope': 'material'})
    asyncio.run(app.material_analysis.execute(run['run_id']))
    with app.repository.read() as c:
        updated = append_supplements(c, sample, old/(tid+'.jsonl.xz'), entry, new)
    lines = lzma.decompress((new/(tid+'.jsonl.xz')).read_bytes()).splitlines()
    assert lines[:len(original)] == original
    assert updated['media'] == entry['media']
    assert any(json.loads(line)[0] == 'material_analysis_runs' for line in lines[len(original):])
    again = tmp_path/'again';again.mkdir()
    with app.repository.read() as c:
        second = append_supplements(c, sample, new/(tid+'.jsonl.xz'), updated, again)
    assert second['sha256'] == updated['sha256']
