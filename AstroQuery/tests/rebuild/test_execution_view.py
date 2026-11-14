"""Cursor isolation, recovery and public diagnostics. All fixtures are offline."""
from uuid import uuid4
import json

import fitz
import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.application.execution_view import project, read, union_seconds
from astroquery_ai.application.execution_report import report, pdf_bytes


@pytest.fixture
def task(tmp_path):
    api = create_app(tmp_path, start_worker=False)
    app = api.state.application
    tid = app.create('SYNTHETIC execution acceptance', str(uuid4()))['task_id']
    return api, app, tid


def job(app, tid, kind='paper_batch', dependencies=None):
    with app.repository.transaction() as c:
        return app.repository.enqueue(c, tid, 'M06', kind, {'work_id': str(uuid4())}, dependencies)


def event(app, tid, kind, **payload):
    with app.repository.transaction() as c:
        return app.repository.event(c, tid, kind, payload)


def test_retry_resource_deferral_and_success_are_different_facts(task):
    _, app, tid = task
    jid = job(app, tid)
    event(app, tid, 'execution_stage_changed', stage_id='extraction')
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    waiting = event(app, tid, 'job_waiting_resource', job_id=jid, seconds=3, new_paid_attempt=False)
    past = project(app, tid, waiting['seq'])
    assert past['summary']['resource_waits'] == 1 and past['summary']['retries'] == 0
    assert past['jobs'][jid]['runs'][0]['status'] == 'waiting_resource'
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    event(app, tid, 'job_retry_scheduled', job_id=jid, reason='MODEL_TIMEOUT')
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    failed = event(app, tid, 'job_state_changed', job_id=jid, status='failed', reason='MODEL_TIMEOUT')
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    event(app, tid, 'job_state_changed', job_id=jid, status='succeeded')
    before = project(app, tid, failed['seq'])
    after = project(app, tid)
    assert before['jobs'][jid]['status'] == 'failed'
    assert before['issues'][0]['recovery'] == 'unresolved'
    assert after['issues'][0]['recovery'] == 'recovered'
    assert after['summary']['retries'] == 1 and after['summary']['run_segments'] == 4
    assert len(before['jobs'][jid]['runs']) == 3


def test_same_timestamp_future_event_is_not_visible(task):
    _, app, tid = task
    jid = job(app, tid)
    first = event(app, tid, 'job_state_changed', job_id=jid, status='failed', reason='MODEL_TIMEOUT')
    second = event(app, tid, 'job_state_changed', job_id=jid, status='succeeded')
    with app.repository.transaction() as c:
        saved = json.loads(c.execute('SELECT payload FROM events WHERE task_id=? AND seq=?', (tid, second['seq'])).fetchone()[0])
        saved['committed_at'] = first['committed_at']
        c.execute('UPDATE events SET payload=? WHERE task_id=? AND seq=?', (json.dumps(saved), tid, second['seq']))
        c.execute("UPDATE jobs SET status='succeeded' WHERE job_id=?", (jid,))
    assert project(app, tid, first['seq'])['jobs'][jid]['status'] == 'failed'
    assert project(app, tid, first['seq'])['issues'][0]['recovery'] != 'recovered'


def test_events_jobs_and_issues_have_independent_filters_and_focus(task):
    _, app, tid = task
    jid = job(app, tid)
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    for _ in range(40):
        event(app, tid, 'batch_committed', candidate_count=1)
    failed = event(app, tid, 'job_state_changed', job_id=jid, status='failed', reason='MODEL_TIMEOUT')
    result = read(app, tid, section='events', stage_id='extraction', focus_seq=failed['seq'], limit=10)
    assert any(r['seq'] == failed['seq'] for r in result['items'])
    assert result['offset'] % 10 == 0
    issues = read(app, tid, section='issues', stage_id='extraction', offset=0)
    assert issues['total'] == 1
    assert read(app, tid, section='jobs', status='failed')['total'] == 1
    assert read(app, tid, section='events', category='exception')['total'] == 1
    assert 'events' not in read(app, tid, section='overview')


def test_public_payload_and_pdf_cannot_include_arbitrary_diagnostics(task):
    api, app, tid = task
    jid = job(app, tid)
    sentinel = 'SECRET_MARKER_76247'
    event(app, tid, 'job_state_changed', job_id=jid, status='failed', reason='Authorization: Bearer ' + sentinel,
          debug={'headers': {'api_key': sentinel}, 'prompt': sentinel}, endpoint='https://private/' + sentinel)
    with TestClient(api) as client:
        for section in ('overview', 'events', 'issues', 'jobs', 'job'):
            response = client.get(f'/api/tasks/{tid}/execution', params={'section':section,'job_id':jid})
            assert response.status_code == 200
            assert sentinel not in response.text and 'Authorization' not in response.text
        legacy = client.get(f'/api/tasks/{tid}/execution')
        assert sentinel not in legacy.text
        response = client.get(f'/api/tasks/{tid}/execution/report')
        assert sentinel not in response.text
        pdf = client.get(f'/api/tasks/{tid}/execution/report?format=pdf')
        assert pdf.status_code == 200
        with fitz.open(stream=pdf.content, filetype='pdf') as doc:
            assert sentinel not in ''.join(p.get_text() for p in doc)
            assert '运行报告' in ''.join(p.get_text() for p in doc)


def test_terminal_only_is_missing_history_not_zero_duration(task):
    _, app, tid = task
    with app.repository.transaction() as c:
        c.execute("UPDATE tasks SET lifecycle='completed' WHERE task_id=?", (tid,))
    p = project(app, tid)
    assert p['wall_seconds'] is None and not p['history_complete']
    assert len(p['stages']) == 8 and not p['visits']
    assert all(s['seconds'] is None for s in p['stages'])


def test_terminal_closes_unknown_runs_without_fake_success(task):
    _, app, tid = task
    jid = job(app, tid)
    event(app, tid, 'execution_stage_changed', stage_id='extraction')
    event(app, tid, 'job_state_changed', job_id=jid, status='running')
    event(app, tid, 'task_state_changed', lifecycle='cancelled')
    p = project(app, tid)
    assert p['jobs'][jid]['status'] == 'ended_unknown'
    assert p['jobs'][jid]['runs'][0]['end'] is None


def test_real_dependencies_and_history_resolution(task):
    _, app, tid = task
    parent = job(app, tid, 'catalog_discover')
    child = job(app, tid, 'literature_discover', [parent])
    before = event(app, tid, 'job_state_changed', job_id=child, status='ready')
    with app.repository.transaction() as c:
        ref = app.repository.put_object(c, tid, 'dependency_resolution', 'r', 1,
            {'resolution':'closed_without_result'})
        c.execute('UPDATE job_dependencies SET resolution=?,resolution_ref=? WHERE job_id=?',
                  ('closed_without_result',json.dumps(ref),child))
        app.repository.event(c, tid, 'dependency_closed', {'resolution_ref':ref})
    assert project(app, tid, before['seq'])['jobs'][child]['dependencies'][0]['resolution'] == 'required'
    assert project(app, tid)['jobs'][child]['dependencies'][0]['job_id'] == parent


def test_report_is_read_only_and_post_terminal_exports_do_not_add_time(task):
    api, app, tid = task
    event(app, tid, 'execution_stage_changed', stage_id='delivery')
    with app.repository.transaction() as c:
        app.repository.mutate_task(c, tid, lifecycle='completed')
        terminal = app.repository.event(c, tid, 'task_state_changed', {'lifecycle':'completed'})
    prior = report(app, tid, terminal['seq'])
    event(app, tid, 'export_updated', format='csv')
    with TestClient(api) as client:
        before = app.view(tid)
        for section in ('overview','events','issues','jobs','services'):
            assert client.get(f'/api/tasks/{tid}/execution',params={'section':section}).status_code == 200
        assert client.get(f'/api/tasks/{tid}/execution/report?format=bad').status_code == 422
        after = app.view(tid)
        assert before['revision'] == after['revision']
        assert before['core_event_cursor'] == after['core_event_cursor']
    assert report(app, tid)['wall_seconds'] == prior['wall_seconds']
    assert report(app, tid)['terminal_seq'] == terminal['seq']


def test_replay_uses_recovered_terminal_and_ignores_later_exports(task):
    from astroquery_ai.application.presentation import replay_clock
    _,app,tid=task
    event(app,tid,'task_state_changed',lifecycle='failed')
    event(app,tid,'task_state_changed',lifecycle='running')
    resumed=event(app,tid,'execution_stage_changed',stage_id='postcheck')
    with app.repository.transaction() as c:
        app.repository.mutate_task(c,tid,lifecycle='completed')
        terminal=app.repository.event(c,tid,'task_state_changed',{'lifecycle':'completed'})
    event(app,tid,'export_updated',format='csv')
    clock=replay_clock(app,tid)
    assert clock['terminal_at']==terminal['committed_at']
    assert clock['timeline'][-1]['seq']==terminal['seq']
    assert any(p['seq']==resumed['seq'] for p in clock['timeline'])


def test_interval_union_counts_overlap_once():
    pairs=[{'start':'2026-11-02T00:00:00+00:00','end':'2026-11-02T00:00:10+00:00'},
           {'start':'2026-11-02T00:00:05+00:00','end':'2026-11-02T00:00:20+00:00'}]
    assert union_seconds(pairs) == 20
    assert union_seconds([]) is None
    assert union_seconds([{'start':pairs[0]['end'],'end':pairs[0]['start']}]) is None


def test_multiple_reviews_keep_the_wait_open_until_all_are_applied(task):
    _, app, tid = task
    event(app, tid, 'execution_stage_changed', stage_id='quality')
    event(app, tid, 'review_ready', review_id='one')
    event(app, tid, 'review_ready', review_id='two')
    event(app, tid, 'task_state_changed', lifecycle='waiting_review')
    first = event(app, tid, 'review_applied', review_id='one')
    last = event(app, tid, 'review_applied', review_id='two')
    event(app, tid, 'fixture_marker')
    waiting = project(app, tid, first['seq'])
    done = project(app, tid, last['seq'])
    assert waiting['waits'][-1]['end'] is None
    assert done['waits'][-1]['end'] == last['committed_at']


def test_republished_review_becomes_pending_again(task):
    _, app, tid = task
    event(app, tid, 'review_ready', review_id='r', revision=1)
    event(app, tid, 'review_withdrawn', review_id='r')
    again = event(app, tid, 'review_ready', review_id='r', revision=2)
    event(app, tid, 'fixture_marker')
    issues = project(app, tid, again['seq'])['issues']
    assert issues[0]['recovery'] == 'unresolved'
