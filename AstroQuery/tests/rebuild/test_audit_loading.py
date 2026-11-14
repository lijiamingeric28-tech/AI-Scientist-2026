"""Display acceleration must preserve exact saved audit and execution facts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astroquery_ai.api.routes.results import register
from astroquery_ai.application.execution_view import read
from astroquery_ai.runtime.delivery import DeliveryService
from tests.rebuild.test_delivery_projection_index import application as base_application
from astroquery_ai.runtime.codec import canonical


def application(tmp_path):
    repo, service, tid, body, api = base_application(tmp_path)
    with repo.transaction() as conn:
        body['quality'] = {'report_ref': repo.put_object(conn, tid, 'quality', 'q', 1,
            {'report_id': 'q', 'schema_version': 'TaskCompletionScore/1', 'score': 87, 'components': []})}
        conn.execute("DELETE FROM objects WHERE task_id=? AND kind='delivery'", (tid,))
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 1, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    return repo, service, tid, body, api


def audit_urls(tid):
    base = f'/api/tasks/{tid}/deliveries/delivery'
    return [base + '/quality', base + '/differences', base + '/changes?view=activity',
            base + '/coverage?view=matrix']


def test_audit_reopen_uses_exact_projection_without_delivery_decode(tmp_path, monkeypatch):
    repo, service, tid, body, api = application(tmp_path)
    with TestClient(api) as client:
        expected = [client.get(url).json() for url in audit_urls(tid)]
    reopened = DeliveryService(repo, service.artifacts)
    original = repo.object
    def no_delivery(conn, task, kind, *args, **kwargs):
        assert kind != 'delivery', 'warm audit reads must not decode the full publication'
        return original(conn, task, kind, *args, **kwargs)
    monkeypatch.setattr(repo, 'object', no_delivery)
    second = FastAPI()
    register(second, SimpleNamespace(repository=repo, delivery=reopened,
        legacy=SimpleNamespace(get=lambda *_: None), history=SimpleNamespace(source=lambda conn, task: task)), None)
    with TestClient(second) as client:
        assert [client.get(url).json() for url in audit_urls(tid)] == expected


def test_audit_revision_validation_and_cache_corruption(tmp_path):
    repo, service, tid, _, api = application(tmp_path)
    with TestClient(api) as client:
        expected = [client.get(url).json() for url in audit_urls(tid)]
        assert client.get(audit_urls(tid)[0] + '?expected_delivery_revision=999').status_code == 409
        service._read_index.path.write_bytes(b'corrupt disposable display data')
        assert [client.get(url).json() for url in audit_urls(tid)] == expected
        service._read_index.path.unlink()
        service._read_index.path.mkdir()
        assert [client.get(url).json() for url in audit_urls(tid)] == expected


def test_frozen_completion_score_can_open_before_audit_index_is_built(tmp_path, monkeypatch):
    repo, service, tid, body, api = application(tmp_path)
    with repo.transaction() as conn:
        score = repo.object(conn, tid, 'quality', 'q', 1)
        body['task_score'] = score
        conn.execute("DELETE FROM objects WHERE task_id=? AND kind='delivery'", (tid,))
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 1, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    with repo.read() as conn:
        service.read_header(conn, tid, 'delivery', 1)
    monkeypatch.setattr(service, 'read_snapshot', lambda *_: pytest.fail('score already exists in validated header'))
    with TestClient(api) as client:
        response = client.get(audit_urls(tid)[0])
        assert response.status_code == 200 and response.json()['body'] == score


def test_execution_sections_share_reconstruction_and_return_independent_results(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    repo = Repository(tmp_path/'runtime.sqlite3')
    app = SimpleNamespace(repository=repo,history=SimpleNamespace(source=lambda conn,task:task))
    tid = repo.create_task('SYNTHETIC execution cache')['task_id']
    with app.repository.transaction() as conn:
        jid = app.repository.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': 'work'})
        failed = app.repository.event(conn, tid, 'job_state_changed', {'job_id': jid, 'status': 'failed'})
    original = app.repository.read
    queries = []
    @contextmanager
    def traced():
        with original() as conn:
            conn.set_trace_callback(queries.append)
            yield conn
    app.repository.read = traced
    read(app, tid, section='overview')
    queries.clear()
    job = read(app, tid, section='job', job_id=jid)
    job['job']['links'].clear()
    assert read(app, tid, section='job', job_id=jid)['job']['links']['work_id'] == 'work'
    read(app, tid, section='events')
    assert not any('SELECT job_id,kind,payload,created_at FROM jobs' in query for query in queries)
    with app.repository.transaction() as conn:
        app.repository.event(conn, tid, 'job_state_changed', {'job_id': jid, 'status': 'succeeded'})
    assert read(app, tid, section='job', job_id=jid)['job']['status'] == 'succeeded'
    assert read(app, tid, failed['seq'], section='job', job_id=jid)['job']['status'] == 'failed'


def test_parallel_audit_misses_decode_once(tmp_path, monkeypatch):
    repo, service, tid, _, api = application(tmp_path)
    original, decoded = repo.object, []
    def count(conn, task, kind, *args, **kwargs):
        if kind == 'delivery':
            decoded.append(1)
        return original(conn, task, kind, *args, **kwargs)
    monkeypatch.setattr(repo, 'object', count)
    # Emulate a large delivery which is intentionally not retained in RAM.
    original_read = service.read_snapshot
    def unretained(*args, **kwargs):
        service._display_key = service._display_body = None
        return original_read(*args, **kwargs)
    monkeypatch.setattr(service, 'read_snapshot', unretained)
    def get(url):
        with TestClient(api) as client:
            response = client.get(url)
            assert response.status_code == 200
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(get, audit_urls(tid)))
    assert len(decoded) == 1


def test_activity_page_filters_all_saved_rows_before_pagination(tmp_path, monkeypatch):
    repo, service, tid, _, api = application(tmp_path)
    entries = [{'id':str(i), 'kind':'human' if i%2 else 'quality', 'property_id':'p',
                'source_ids':['s1'], 'measurement_ids':['m00000'], 'at':None,
                'actual_change':False, 'status':'recorded'} for i in range(65)]
    monkeypatch.setattr('astroquery_ai.application.research_views.activities', lambda *a: entries)
    with TestClient(api) as client:
        base = audit_urls(tid)[2]
        old = client.get(base).json()
        assert old['items'] == entries
        page = client.get(base+'&projection=page&action=human&offset=20&limit=10').json()
        assert page['total'] == 32
        assert page['matched_measurements'] == 1
        assert [x['id'] for x in page['items']] == [str(i) for i in range(41,60,2)]
        assert len(page['records']) == 1
        assert client.get(base+'&activity_kind=human').json()['total'] == 32
        assert client.get(base+'&projection=page&property_id=missing').json()['total'] == 0
        assert client.get(base+'&projection=page&source_id=missing').json()['total'] == 0
        assert client.get(base+'&projection=page&activity_start=invalid').status_code == 422


def test_execution_concurrent_sections_build_once_and_same_cursor_metadata_invalidates(tmp_path, monkeypatch):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.application import execution_view
    from threading import Barrier
    repo = Repository(tmp_path/'runtime.sqlite3')
    app = SimpleNamespace(repository=repo,history=SimpleNamespace(source=lambda conn,task:task))
    tid = repo.create_task('SYNTHETIC concurrent execution')['task_id']
    with repo.transaction() as conn:
        jid=repo.enqueue(conn,tid,'M06','paper_batch',{'work_id':'before'})
        repo.event(conn,tid,'job_state_changed',{'job_id':jid,'status':'succeeded'})
    original,calls,barrier=execution_view._project,[],Barrier(4)
    def count(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(execution_view,'_project',count)
    def section(name):
        barrier.wait(timeout=10)
        return read(app,tid,section=name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(section,['overview','jobs','events','issues']))
    assert len(calls)==1
    with repo.transaction() as conn:
        conn.execute('UPDATE jobs SET payload=? WHERE job_id=?',(canonical({'work_id':'after'}),jid))
    assert read(app,tid,section='job',job_id=jid)['job']['links']['work_id']=='after'
    assert len(calls)==2
    import json
    with repo.transaction() as conn:
        event=conn.execute('SELECT seq,payload FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 1',(tid,)).fetchone()
        payload=json.loads(event['payload']);payload['payload']['status']='failed'
        conn.execute('UPDATE events SET payload=? WHERE task_id=? AND seq=?',(canonical(payload),tid,event['seq']))
    assert read(app,tid,section='job',job_id=jid)['job']['status']=='failed'


def test_audit_review_metadata_changes_invalidate_without_republishing_delivery(tmp_path, monkeypatch):
    repo, service, tid, _, api = application(tmp_path)
    from astroquery_ai.application import research_views
    original,calls=research_views.activities,[]
    def count(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(research_views,'activities',count)
    with TestClient(api) as client:
        url=audit_urls(tid)[2]
        expected=client.get(url).json()
        assert client.get(url).json()==expected and len(calls)==1
        with repo.transaction() as conn:
            conn.execute("INSERT INTO reviews(review_id,task_id,revision,basis_hash,logical_key,status,payload) "
                         "VALUES(?,?,1,'basis','review-key','pending',?)",('r',tid,canonical({'revision':1})))
        assert client.get(url).json()==expected and len(calls)==2
        with repo.transaction() as conn:
            conn.execute("UPDATE reviews SET payload=? WHERE review_id='r'",(canonical({'revision':2}),))
        assert client.get(url).json()==expected and len(calls)==3
