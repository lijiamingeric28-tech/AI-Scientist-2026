"""HTTP reads of a pinned delivery reuse a disposable normalized projection."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from astroquery_ai.api.routes.results import register
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_presentation_read_cache import committed_clock
from tests.rebuild.test_result_read_index import setup_delivery


def application(tmp_path, *, padding=0):
    repo, service, tid, body = setup_delivery(tmp_path, 4)
    body.update(status='completed', counts={'records': 4}, figures=[{'figure_id': 'f1', 'source_id': 's1'}])
    body['contexts'] = [{'context_id': 'c', 'conditions': []}]
    body['provenance_bundle'].update(interpretations=[{'interpretation_id': 'i1'}], human_answers=[])
    for record in body['measurements']:
        record['evidence_refs'] = []
    if padding:
        body['test_padding'] = 'x' * padding
    with repo.transaction() as conn:
        conn.execute("DELETE FROM objects WHERE task_id=? AND kind='delivery'", (tid,))
        diff = repo.put_object(conn, tid, 'difference', 'diff', 1, {'comparison_projection': {'groups': [], 'limitations': []}})
        body['difference'] = {'report_ref': diff}
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 1, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    app = FastAPI()
    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse(exc.as_dict(), status_code=exc.status)
    register(app, SimpleNamespace(repository=repo, delivery=service,
        legacy=SimpleNamespace(get=lambda *_: None), history=SimpleNamespace(source=lambda conn, task: task)), None)
    return repo, service, tid, body, app


def reads(tid):
    base = f'/api/tasks/{tid}/deliveries/delivery'
    return [f'/api/tasks/{tid}/delivery', base + '/materials?view=workbench&candidates_only=true',
        base + '/materials?view=workbench&material_id=s1&property_id=p-temperature',
        base + '/records?record_id=m00000', base + '/sources?source_id=s1', base + '/figures?figure_id=f1']


def test_header_workbench_and_exact_details_survive_reopen_without_delivery_decode(tmp_path, monkeypatch):
    repo, service, tid, body, app = application(tmp_path)
    with TestClient(app) as client:
        expected = [client.get(url).json() for url in reads(tid)]
    # Every kind shares the same completed projection, including across service restarts.
    reopened = DeliveryService(repo, service.artifacts)
    original = repo.object
    def no_delivery(conn, task, kind, *args, **kwargs):
        assert kind != 'delivery', 'projection hit must not decode the delivery body'
        return original(conn, task, kind, *args, **kwargs)
    monkeypatch.setattr(repo, 'object', no_delivery)
    app2 = FastAPI()
    register(app2, SimpleNamespace(repository=repo, delivery=reopened,
        legacy=SimpleNamespace(get=lambda *_: None), history=SimpleNamespace(source=lambda conn, task: task)), None)
    with TestClient(app2) as client:
        assert [client.get(url).json() for url in reads(tid)] == expected


def test_large_snapshot_cross_resource_construction_decodes_once(tmp_path, monkeypatch):
    repo, service, tid, _, app = application(tmp_path, padding=129 * 1024 * 1024)
    original, calls, barrier = repo.object, [], Barrier(4)
    def count(conn, task, kind, *args, **kwargs):
        if kind == 'delivery':
            calls.append(1)
        return original(conn, task, kind, *args, **kwargs)
    monkeypatch.setattr(repo, 'object', count)
    def get(url):
        barrier.wait(timeout=20)
        with TestClient(app) as client:
            response = client.get(url)
            assert response.status_code == 200
            return response.json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(get, reads(tid)[:4]))
    assert len(calls) == 1
    assert service._display_body is None


def test_summary_projection_is_small_dynamic_and_validated_before_304(tmp_path):
    repo, service, tid, body, app = application(tmp_path)
    from astroquery_ai.science.material_summaries import _identity
    with TestClient(app) as client:
        url = reads(tid)[2] + '&projection=summary'
        first = client.get(url)
        assert set(first.json()) == {'delivery_id', 'delivery_revision', 'snapshot_ref', 'summary'}
        assert client.get(url, headers={'If-None-Match': first.headers['etag']}).status_code == 304
        with repo.transaction() as conn:
            repo.put_object(conn, tid, 'material_summary', _identity(body, 's1', 'p-temperature'), 1,
                {'state': 'ready', 'text': 'A saved introduction'})
        second = client.get(url, headers={'If-None-Match': first.headers['etag']})
        assert second.status_code == 200 and second.json()['summary']['text'] == 'A saved introduction'
        assert client.get(url + '&expected_delivery_revision=2', headers={'If-None-Match': second.headers['etag']}).status_code == 409
        assert client.get(url + '&at_seq=999999', headers={'If-None-Match': second.headers['etag']}).status_code == 409


def test_projection_corruption_and_unavailable_disk_preserve_response(tmp_path):
    repo, service, tid, _, app = application(tmp_path)
    with TestClient(app) as client:
        expected = [client.get(url).json() for url in reads(tid)]
        service._read_index.path.write_bytes(b'damaged disposable cache')
        assert [client.get(url).json() for url in reads(tid)] == expected
        service._read_index.path.unlink()
        service._read_index.path.mkdir()
        assert [client.get(url).json() for url in reads(tid)] == expected


def test_default_record_contract_equals_authoritative_route_and_keeps_saved_order(tmp_path, monkeypatch):
    repo, service, tid, body, app = application(tmp_path)
    # Interleaved evidence views, alias citations and shared exact contexts expose
    # accidental regrouping, incomplete reference expansion and duplicated text.
    body = deepcopy(body)
    body['revision'] = 2
    body['evidence_index'] = [{'evidence_id': eid, 'source_id': 's1', 'raw_text': eid * 50000}
                              for eid in ('e1', 'e2')]
    body['evidence_views'] = [{'evidence_id': 'e1', 'label': 'first'}, {'evidence_id': 'e2', 'label': 'second'},
                              {'evidence_id': 'e1', 'label': 'third'}]
    body['provenance_bundle'].update(
        reported_references=[{'reference_id': 'z', 'measurement_id': 'old', 'cited_work_id': 'work'},
                             {'reference_id': 'a', 'measurement_id': 'unrelated'}],
        source_mentions=[{'original_measurement_ref': {'id': 'old'}, 'measurement_id': 'm00000'}],
        cited_works=[{'cited_work_id': 'work', 'title': 'Saved cited work'}],
        source_statements=[{'statement_id': 'statement', 'text': 'Saved method'}])
    body['contexts'][0]['source_statements'] = [{'id': 'statement'}]
    body['measurements'][0].update(evidence_refs=[{'id': 'e2'}, {'id': 'e1'}], lineage_refs=[{'id': 'a'}])
    for record in body['measurements'][1:]:
        record['evidence_refs'] = [{'id': 'e1'}]
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    optimized = service.read_detail_resource
    base = f'/api/tasks/{tid}/deliveries/delivery/records'
    urls = [base, base + '?offset=1&limit=2', base + '?record_id=m00000',
            base + '?view=summary', base + '?record_id=m00000&view=summary']
    with TestClient(app) as client:
        monkeypatch.setattr(service, 'read_detail_resource', lambda *args, **kwargs: None)
        original = [client.get(url).json() for url in urls]
        monkeypatch.setattr(service, 'read_detail_resource', optimized)
        assert [client.get(url).json() for url in urls] == original
        detail = client.get(urls[2]).json()['items'][0]
        assert [v['label'] for v in detail['evidence_views']] == ['first', 'second', 'third']
        assert [r['reference_id'] for r in detail['reported_references']] == ['z', 'a']
        detail['property_binding']['definition']['name_cn'] = 'Consumer mutation'
        assert client.get(urls[2]).json()['items'][0]['property_binding']['definition']['name_cn'] == '有效温度'
    import sqlite3
    with sqlite3.connect(service._read_index.path) as conn:
        assert conn.execute("SELECT count(*) FROM delivery_values WHERE CAST(payload AS TEXT) LIKE '%raw_text%e1e1e1%'").fetchone()[0] == 1


def test_conditional_summary_checks_authoritative_hash_and_task_before_hit(tmp_path):
    import json
    repo, service, tid, body, app = application(tmp_path)
    with TestClient(app) as client:
        url = reads(tid)[2] + '&projection=summary'
        first = client.get(url)
        with repo.transaction() as conn:
            reference = json.loads(repo.task(conn, tid)['delivery_ref'])
            reference['content_sha256'] = '0' * 64
            conn.execute('UPDATE tasks SET delivery_ref=? WHERE task_id=?', (canonical(reference).decode(), tid))
        changed = client.get(url, headers={'If-None-Match': first.headers['etag']})
        assert changed.status_code == 409 and changed.json()['code'] == 'OBJECT_HASH_MISMATCH'


def test_public_header_keeps_current_pointer_requirement_after_trusted_snapshot_read(tmp_path):
    repo, service, tid, body, app = application(tmp_path)
    with repo.transaction() as conn:
        _, ref = service.delivery_reference(conn, tid)
        repo.event(conn, tid, 'delivery_ready', {'delivery_ref': ref})
        conn.execute('UPDATE tasks SET delivery_ref=NULL WHERE task_id=?', (tid,))
    with repo.read() as conn:
        assert service.read_snapshot(conn, tid, 'delivery', 1)['snapshot_ref'] == body['snapshot_ref']
    with TestClient(app) as client:
        response = client.get(reads(tid)[0])
        assert response.status_code == 409 and response.json()['code'] == 'RESULT_NOT_READY'


@pytest.mark.parametrize('resource', ['sources', 'figures'])
def test_partial_historical_snapshot_uses_existing_resource_contract(tmp_path, resource):
    repo, service, tid, _, app = application(tmp_path)
    item = {'source_id': 'old-source', 'title': ['Saved source']} if resource == 'sources' else {'figure_id': 'old-figure'}
    body = {'delivery_id': 'delivery', 'revision': 2, 'snapshot_ref': {'id': 'old-snapshot'}, resource: [item]}
    if resource == 'figures':
        body['figure_coverage'] = [{'state': 'available'}]
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    with TestClient(app) as client:
        response = client.get(f'/api/tasks/{tid}/deliveries/delivery/{resource}')
        assert response.status_code == 200
        result = response.json()
        expected = item if resource == 'sources' else {**item, 'image_url': None, 'page_url': None, 'pdf_url': None}
        assert result['items'] == [expected] and result['total'] == 1
        assert result['snapshot_ref'] == body['snapshot_ref']
        if resource == 'sources':
            listing = client.get(f'/api/tasks/{tid}/deliveries/delivery/sources?view=list')
            assert listing.status_code == 200 and listing.json()['items'] == [item]
        else:
            assert result['coverage'] == body['figure_coverage']
    import sqlite3
    with sqlite3.connect(service._read_index.path) as conn:
        assert conn.execute('SELECT count(*) FROM delivery_projections').fetchone()[0] == 0


def test_partial_header_preserves_original_counts_without_requiring_detail_sections(tmp_path):
    repo, service, tid, _, app = application(tmp_path)
    body = {'delivery_id': 'delivery', 'revision': 2, 'snapshot_ref': {'id': 'old-snapshot'},
            'status': 'completed', 'counts': {'saved': 1}, 'definitions': [],
            'measurements': [{'measurement_id': 'old-record'}], 'sources': [], 'figures': []}
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    with TestClient(app) as client:
        response = client.get(reads(tid)[0])
        assert response.status_code == 200
        assert response.json()['counts'] == body['counts']
        assert response.json()['display_counts'] == {'records': 1, 'sources': 0, 'figures': 0, 'materials': 0}


def test_present_malformed_sections_are_not_treated_as_inapplicable_projection(tmp_path):
    repo, service, tid, body, app = application(tmp_path)
    body = {**body, 'revision': 2, 'definitions': None}
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    with TestClient(app) as client, pytest.raises(TypeError):
        client.get(f'/api/tasks/{tid}/deliveries/delivery/sources')


@pytest.mark.parametrize('saved_counts', [False, True])
def test_presentation_header_overview_equals_existing_cutoff_semantics(tmp_path, saved_counts, monkeypatch):
    from astroquery_ai.science.material_summaries import _identity
    repo, service, tid, body, _ = application(tmp_path)
    body = deepcopy(body)
    body['revision'] = 2
    body['insight_report'] = {'schema_version': 'MaterialSummaryReport/1', 'status': 'pending'}
    if saved_counts:
        body['insight_report']['counts'] = {'p-temperature': {'requested': 3, 'ready': 0, 'failed': 0}}
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
        repo.put_object(conn, tid, 'material_summary', _identity(body, 's1', 'p-temperature'), 1,
            {'state': 'ready', 'snapshot_ref': body['snapshot_ref'], 'property_id': 'p-temperature'})
    with repo.read() as conn:
        expected = service.material_overview(conn, tid, body, as_of='9999')
        assert service.read_header(conn, tid, 'delivery', 2, as_of='9999')['material_overview'] == expected
    def forbidden(*args, **kwargs):
        raise AssertionError('presentation header hit must not decode full snapshot')
    monkeypatch.setattr(service, 'read_snapshot', forbidden)
    with repo.read() as conn:
        assert service.read_header(conn, tid, 'delivery', 2, as_of='9999')['material_overview'] == expected


def test_activity_answer_membership_indexes_interpretations_once_preserving_any_match():
    from astroquery_ai.application.research_views import activities
    class CountedInterpretations(list):
        passes = 0
        def __iter__(self):
            self.passes += 1
            return super().__iter__()
    interpretations = CountedInterpretations([
        {'interpretation_id': 'shared', 'human_answer_ref': {'id': 'a'}},
        {'interpretation_id': 'shared', 'human_answer_ref': {'id': 'b'}},
        {'interpretation_id': 'other', 'human_answer_ref': {'id': 'a'}},
    ])
    records = [{'measurement_id': f'm{i}', 'interpretation_ref': {'id': iid},
                'source_ref': {'id': 's'}, 'property_ref': {'id': 'p'}}
               for i, iid in enumerate(('shared', 'other', 'shared'))]
    rows = activities({'revision': 1, 'snapshot_ref': {}, 'measurements': records,
        'provenance_bundle': {'interpretations': interpretations,
                              'human_answers': [{'answer_id': 'a'}, {'answer_id': 'b'}]}})
    assert [(r['id'], r['measurement_ids']) for r in rows if r['kind'] == 'human'] == [
        ('a', ['m0', 'm1', 'm2']), ('b', ['m0', 'm2'])]
    assert interpretations.passes == 1


def test_reversed_list_and_projection_stripes_complete_in_subprocess(tmp_path):
    """Two cold publications must not wait on each other's outer list lock."""
    import subprocess
    import sys
    script = r'''
import sys
from threading import Barrier, Thread
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.result_index import ResultReadIndex, PROJECTION_PROTOCOL
from astroquery_ai.runtime.delivery_index import DeliveryProjectionIndex, PROTOCOL

seen = {}
for candidate in range(20000):
    identity = (f'task-{candidate}', 'delivery', 1, 'hash')
    pair = (int(digest([*identity, 'records', 'list', PROJECTION_PROTOCOL])[:8], 16) % 64,
            int(digest([*identity, PROTOCOL, PROJECTION_PROTOCOL])[:8], 16) % 64)
    if pair[0] != pair[1] and pair[::-1] in seen:
        identities = [seen[pair[::-1]], identity]
        break
    seen[pair] = identity
else:
    raise AssertionError('No reversed stripes found for the current projection protocol')
pairs = [(int(digest([*identity, 'records', 'list', PROJECTION_PROTOCOL])[:8], 16) % 64,
          int(digest([*identity, PROTOCOL, PROJECTION_PROTOCOL])[:8], 16) % 64)
         for identity in identities]
assert pairs[0] == pairs[1][::-1] and pairs[0][0] != pairs[0][1], pairs
index = ResultReadIndex(sys.argv[1])
index._connect().close()
projections = DeliveryProjectionIndex(index)
barrier = Barrier(3)
results, failures = [], []
def read(identity):
    def builder():
        barrier.wait(timeout=5)
        return projections.read(identity, lambda: iter([('header', '', {'x': 1})]),
                                lambda reader: ([], {'resource': 'records'}))
    try:
        results.append(index.read((*identity, 'records', 'list'), builder))
    except BaseException as error:
        failures.append(repr(error))
threads = [Thread(target=read, args=(identity,), daemon=True) for identity in identities]
for thread in threads:
    thread.start()
barrier.wait(timeout=5)
for thread in threads:
    thread.join(timeout=3)
assert not any(thread.is_alive() for thread in threads), ('reversed-stripe deadlock', pairs)
assert not failures and len(results) == 2, (failures, results)
'''
    completed = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'cache.sqlite3')],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_detail_values_and_partial_marker_corruption_rebuild_atomically(tmp_path, monkeypatch):
    import sqlite3
    repo, service, tid, _, app = application(tmp_path)
    original, calls = repo.object, []
    def count(conn, task, kind, *args, **kwargs):
        if kind == 'delivery':
            calls.append(1)
        return original(conn, task, kind, *args, **kwargs)
    monkeypatch.setattr(repo, 'object', count)
    with TestClient(app) as client:
        url = reads(tid)[3]
        expected = client.get(url).json()
        for damage in ("DELETE FROM delivery_items WHERE kind='figure'",
                       "UPDATE delivery_values SET payload=x'7b7d'"):
            service._display_key = service._display_body = None
            calls.clear()
            with sqlite3.connect(service._read_index.path) as conn:
                conn.execute(damage)
            assert client.get(url).json() == expected
            assert len(calls) == 1


def test_mid_build_disk_failure_uses_same_decode_then_can_rebuild(tmp_path, monkeypatch):
    import sqlite3
    from astroquery_ai.runtime.delivery_index import DeliveryProjectionIndex
    repo, service, tid, _, app = application(tmp_path)
    build = DeliveryProjectionIndex._build
    original, calls, attempts = repo.object, [], []
    def count(conn, task, kind, *args, **kwargs):
        if kind == 'delivery':
            calls.append(1)
        return original(conn, task, kind, *args, **kwargs)
    def fail_once(conn, key, builder):
        attempts.append(1)
        if len(attempts) == 1:
            # Consume part of the generator, which has decoded the source, then
            # simulate a disk write failing before its completion marker.
            next(iter(builder()))
            raise sqlite3.OperationalError('simulated disk full')
        return build(conn, key, builder)
    monkeypatch.setattr(repo, 'object', count)
    monkeypatch.setattr(DeliveryProjectionIndex, '_build', staticmethod(fail_once))
    with TestClient(app) as client:
        assert client.get(reads(tid)[0]).json()['display_counts']['records'] == 4
        assert len(calls) == 1 and len(attempts) == 2
        # Retry persists a complete entry, and a later hit performs no build.
        assert client.get(reads(tid)[0]).status_code == 200
        before = len(attempts)
        assert client.get(reads(tid)[0]).status_code == 200
        assert len(attempts) == before


def test_summary_reads_only_small_projection_and_preserves_definition_order(tmp_path, monkeypatch):
    from astroquery_ai.runtime.delivery_index import ProjectionReader
    repo, service, tid, body, app = application(tmp_path)
    body = deepcopy(body)
    body['revision'] = 2
    extra = deepcopy(body['definitions'][0])
    extra.update(property_id='aaa-first-alphabetically')
    body['definitions'].append(extra)
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    with TestClient(app) as client:
        listing = client.get(reads(tid)[1]).json()
        assert listing['selected_property_id'] == 'p-temperature'
        assert [p['property_id'] for p in listing['properties']] == ['p-temperature', 'aaa-first-alphabetically']
        get, kinds = ProjectionReader.get, []
        def inspect(reader, kind, *args):
            kinds.append(kind)
            assert kind not in {'material_state', 'material', 'detail', 'source', 'figure'}
            return get(reader, kind, *args)
        monkeypatch.setattr(ProjectionReader, 'get', inspect)
        response = client.get(reads(tid)[2] + '&projection=summary')
        assert response.status_code == 200
        assert set(kinds) == {'header', 'material_resolver', 'summary_group'}


def test_summary_history_same_id_revisions_and_replay_capture_before_304(tmp_path, committed_clock):
    from astroquery_ai.science.material_summaries import _identity
    repo, service, tid, body, app = application(tmp_path)
    replay = repo.create_task('SYNTHETIC captured projection', kind='replay')['task_id']
    with repo.transaction() as conn:
        _, ref = service.delivery_reference(conn, tid)
        published = repo.event(conn, tid, 'delivery_ready', {'delivery_ref': ref})
        repo.put_object(conn, replay, 'replay_snapshot', replay, 1, {'source_delivery_ref': ref,
            'created_at': published['committed_at'], 'source_view': {'core_event_cursor': published['seq']}})
        conn.execute('INSERT INTO replay_sources VALUES(?,?,?)', (replay, tid, '{}'))
        repo.put_object(conn, tid, 'material_summary', _identity(body, 's1', 'p-temperature'), 1,
                        {'state': 'ready', 'text': 'A summary after replay capture'})
        frame = repo.event(conn, tid, 'material_summary_updated', {})
    url = reads(tid)[2] + '&projection=summary&delivery_revision=1'
    with TestClient(app) as client:
        live = client.get(url)
        assert live.json()['summary']['state'] == 'ready'
        sealed = client.get(url + '&sealed_only=true')
        assert sealed.json()['summary']['state'] == 'unavailable'
        saved_url = url.replace(tid, replay)
        saved = client.get(saved_url)
        assert saved.json()['summary']['state'] == 'unavailable'
        assert client.get(saved_url + f'&at_seq={frame["seq"]}',
                          headers={'If-None-Match': saved.headers['etag']}).status_code == 409
        with repo.transaction() as conn:
            later = deepcopy(body)
            later.update(revision=2, sources=[{**s, 'title': ['Revision two']} for s in body['sources']])
            ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, later)
            repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
        assert client.get(url).json()['summary']['state'] == 'unavailable'
        historical = client.get(url + f'&at_seq={frame["seq"]}')
        assert historical.json()['summary']['state'] == 'ready'
        source = f'/api/tasks/{tid}/deliveries/delivery/sources?source_id=s1'
        assert client.get(source + '&delivery_revision=1').json()['items'][0]['title'] == ['Alpha source']
        assert client.get(source + '&delivery_revision=2').json()['items'][0]['title'] == ['Revision two']
