"""Paging must select globally and keep the sealed values and export scope exact."""
from copy import deepcopy
from uuid import uuid4
import json

import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from tests.rebuild.test_research_exports import fixture


def setup_delivery(tmp_path, count=5000):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    service = DeliveryService(repo, ArtifactStore(tmp_path / 'artifacts', repo))
    tid = repo.create_task('SYNTHETIC indexed results')['task_id']
    body = fixture()
    body.update(task_id=tid, revision=1, evidence_index=[])
    template = body['measurements'][0]
    body['measurements'] = []
    body['sources'] = [
        {'source_id': 's1', 'title': ['Alpha source'], 'year': 2001},
        {'source_id': 's2', 'title': ['Beta source'], 'year': 2025},
        {'source_id': 's3', 'title': ['Undated source']}]
    for i in range(count):
        row = deepcopy(template)
        row.update(measurement_id=f'm{i:05}', revision=1, content_sha256=f'h{i}',
                   source_ref={'id': f's{i % 3 + 1}'}, context_ref={'id': 'c'},
                   target_ref={'id': 'target'}, raw_value=str(i), value={'kind': 'real', 'value': str(i)})
        body['measurements'].append(row)
    body['archive_groups'] = [{'group_id': 'g', 'member_refs': [{'id': 'm00000'}, {'id': 'm04999'}],
                               'display_anchor': {'id': 'm00000'}, 'reason': 'saved evidence'}] if count == 5000 else []
    body['dispositions'] = [{'report_only': True, 'snapshot_ref': body['snapshot_ref'],
                             'measurement_ref': {'id': 'm00002', 'version': 1, 'content_sha256': 'h2'},
                             'status': 'not_supported'}]
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', body['delivery_id'], 1, body)
        repo.mutate_task(conn, tid, lifecycle='running', science_state='sealed', delivery_ref=canonical(ref).decode())
    return repo, service, tid, body


def page(repo, service, tid, **kwargs):
    with repo.read() as conn:
        return service.read_page(conn, tid, 'delivery', 'records', **kwargs)


def test_5000_rows_page_and_warm_reopen_do_not_project_all_rows(tmp_path, monkeypatch):
    repo, service, tid, body = setup_delivery(tmp_path)
    first = page(repo, service, tid, limit=50)
    assert first['total'] == 5000 and len(first['items']) == 50
    assert first['offset'] == 0 and first['limit'] == 50
    assert first['aggregates']['owner_excluded'] == 1
    assert first['aggregates']['duplicate'] == 2
    assert first['items'][0]['source_label']['title'] == ['Alpha source']
    assert first['items'][0]['flags']['duplicate']
    assert len(canonical(first)) < 256 * 1024
    def forbidden(*args, **kwargs):
        raise AssertionError('warm index must not decode or project whole delivery')
    reopened = DeliveryService(repo, service.artifacts)
    monkeypatch.setattr(reopened, 'read_snapshot', forbidden)
    later = page(repo, reopened, tid, offset=4950, limit=50)
    assert later['items'][-1]['source']['measurement_id'] == 'm04999'
    assert later['snapshot_ref'] == body['snapshot_ref']


@pytest.mark.parametrize(('filters', 'ids'), [
    ({'q': 'm04999'}, ['m04999']),
    ({'q': ' BETA SOURCE ', 'record_id': 'm00001'}, ['m00001']),
    ({'q': '论文提取', 'record_id': 'm00001'}, ['m00001']),
    ({'quick': 'duplicate'}, ['m00000', 'm04999']),
    ({'quick': 'modified'}, ['m00000', 'm04999']),
    ({'quick': 'target', 'record_id': 'm00002'}, []),
    ({'field': '有效温度', 'record_id': 'm00002'}, ['m00002']),
    ({'field': 'other'}, []),
    ({'year_sort': 'desc'}, ['m00001', 'm00004']),
    ({'year_sort': 'asc'}, ['m00000', 'm00003']),
])
def test_full_result_predicates_and_stable_year_sort(tmp_path, filters, ids):
    repo, service, tid, _ = setup_delivery(tmp_path)
    result = page(repo, service, tid, filters=filters, limit=2)
    assert [r['source']['measurement_id'] for r in result['items']] == ids


def test_corrupt_cache_rebuilds_and_exact_revision_hash_isolated(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    assert page(repo, service, tid)['total'] == 3
    cache = tmp_path / 'cache' / 'ui-read-models.sqlite3'
    cache.write_bytes(b'broken sqlite cache')
    assert page(repo, service, tid)['total'] == 3
    new = deepcopy(body)
    new.update(revision=2, measurements=body['measurements'][:1])
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, new)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    assert page(repo, service, tid)['total'] == 1
    assert page(repo, service, tid, revision=1)['total'] == 3
    with pytest.raises(DomainError, match='交付'):
        page(repo, service, tid, expected_revision=1)


def test_filtered_export_all_matching_minus_exclusions_and_replay(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 6)
    request = {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
               'expected_delivery_revision': 1, 'format': 'json', 'export_schema_version': 1,
               'selection': {'mode': 'filtered', 'filter_version': 1,
                             'filters': {'source_id': 's1'}, 'excluded_measurement_ids': ['m00000']}}
    result = service.export(tid, request)
    assert result['selected_count'] == 1 and result['selection']['selected_ids'] == ['m00003']
    assert service.export(tid, request) == result
    raw = service.artifacts.path(result['artifacts'][0]['relative_path']).read_bytes()
    assert json.loads(raw)['measurements'] == [body['measurements'][3]]
    assert json.loads(raw)['export_selection']['original_report_scope'] == body['snapshot_ref']
    for patch in [
        {'filter_version': 2}, {'filters': {'offset': 0}}, {'filters': {'quick': 'bogus'}},
        {'filters': {'q': []}}, {'excluded_measurement_ids': ['m00000', 'm00000']},
        {'excluded_measurement_ids': ['m00001']}, {'excluded_measurement_ids': ['m00000', 'm00003']},
        {'filters': {'q': 'nothing-matches'}},
    ]:
        with pytest.raises(DomainError):
            service.export(tid, {**request, 'operation_id': str(uuid4()),
                                'selection': {**request['selection'], **patch}})
    with pytest.raises(DomainError) as error:
        service.export(tid, {**request, 'operation_id': str(uuid4()), 'expected_delivery_revision': 2})
    assert error.value.code == 'DELIVERY_CHANGED'


def test_archive_collapse_pages_first_matching_member_but_export_keeps_members(tmp_path):
    repo, service, tid, _ = setup_delivery(tmp_path)
    result = page(repo, service, tid, filters={'quick': 'duplicate', 'year_sort': 'desc'},
                  collapse_duplicates=True, limit=1)
    assert result['total'] == 2 and result['display_total'] == 1
    assert result['items'][0]['source']['measurement_id'] == 'm04999'
    assert page(repo, service, tid, filters={'quick': 'duplicate', 'source_id': 's1'},
                collapse_duplicates=True)['items'][0]['source']['measurement_id'] == 'm00000'
    assert page(repo, service, tid, filters={'fields': []})['total'] == 0
    assert page(repo, service, tid, filters={'fields': ['有效温度'], 'source_group': 'paper'})['total'] == 5000


def test_index_protocol_change_and_partial_entry_rebuild(tmp_path, monkeypatch):
    import sqlite3
    from astroquery_ai.runtime import result_index
    repo, service, tid, _ = setup_delivery(tmp_path, 3)
    assert page(repo, service, tid)['total'] == 3
    with sqlite3.connect(tmp_path / 'cache' / 'ui-read-models.sqlite3') as conn:
        conn.execute('DELETE FROM rows WHERE position=2')
    assert page(repo, service, tid)['total'] == 3
    monkeypatch.setattr(result_index, 'PROJECTION_PROTOCOL', 'test-new-protocol')
    assert page(repo, service, tid)['total'] == 3
    with sqlite3.connect(tmp_path / 'cache' / 'ui-read-models.sqlite3') as conn:
        assert conn.execute('SELECT count(*) FROM entries').fetchone()[0] == 2


def test_filtered_export_rechecks_revision_after_serialization(tmp_path, monkeypatch):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    original = service._serialize
    def serialize(*args, **kwargs):
        result = original(*args, **kwargs)
        with repo.transaction() as conn:
            ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, {**body, 'revision': 2})
            repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
        return result
    monkeypatch.setattr(service, '_serialize', serialize)
    request = {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
               'expected_delivery_revision': 1, 'format': 'json', 'export_schema_version': 1,
               'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {}, 'excluded_measurement_ids': []}}
    with pytest.raises(DomainError) as error:
        service.export(tid, request)
    assert error.value.code == 'DELIVERY_CHANGED'
    with repo.read() as conn:
        assert repo.objects(conn, tid, 'export') == []


def test_replay_cannot_generate_a_new_export(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    replay = repo.create_task('SYNTHETIC replay', kind='replay')['task_id']
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 1, body)
        repo.put_object(conn, replay, 'replay_snapshot', replay, 1, {'source_delivery_ref': ref})
        conn.execute('INSERT INTO replay_sources VALUES(?,?,?)', (replay, tid, '{}'))
    with pytest.raises(DomainError) as error:
        service.export(replay, {'operation_id': str(uuid4()), 'task_id': replay, 'delivery_id': 'delivery',
            'expected_delivery_revision': 1, 'format': 'json', 'export_schema_version': 1,
            'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {}, 'excluded_measurement_ids': []}})
    assert error.value.code == 'TASK_READ_ONLY'


def test_routes_page_conditional_revision_validation_and_source_detail(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from astroquery_ai.api.routes.results import register
    repo, service, tid, _ = setup_delivery(tmp_path, 6)
    app = FastAPI()
    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(error.as_dict(), status_code=error.status)
    register(app, SimpleNamespace(repository=repo, delivery=service,
        legacy=SimpleNamespace(get=lambda *_: None), history=SimpleNamespace(source=lambda conn, tid: tid)), None)
    with TestClient(app) as client:
        url = f'/api/tasks/{tid}/deliveries/delivery/records?view=list&limit=2&q=Alpha'
        response = client.get(url)
        assert response.status_code == 200 and response.json()['total'] == 2
        assert client.get(url, headers={'If-None-Match': response.headers['ETag']}).status_code == 304
        assert client.get(url + '&expected_delivery_revision=2',
                          headers={'If-None-Match': response.headers['ETag']}).status_code == 409
        assert client.get(url + '&fields=wrong').status_code == 422
        source = client.get(f'/api/tasks/{tid}/deliveries/delivery/sources?source_id=s2').json()
        assert source['items'] == [{'source_id': 's2', 'title': ['Beta source'], 'year': 2025}]


def test_same_version_singleflight_build_and_cache_failure_fallback(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from astroquery_ai.application import result_views
    repo, service, tid, _ = setup_delivery(tmp_path, 30)
    original = result_views.record_list
    calls = []
    barrier = Barrier(4)
    def project(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(result_views, 'record_list', project)
    def read(offset):
        barrier.wait(timeout=10)
        return page(repo, service, tid, offset=offset, limit=5)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, [0, 5, 10, 15]))
    assert [r['items'][0]['source']['measurement_id'] for r in results] == ['m00000', 'm00005', 'm00010', 'm00015']
    assert len(calls) == 1
    # A directory at the exact disposable cache path simulates unavailable disk.
    service._read_index.path.unlink()
    service._read_index.path.mkdir()
    assert page(repo, service, tid, filters={'q': 'm00029'})['total'] == 1


def test_legacy_filters_use_saved_modifications_duplicates_and_labels(tmp_path):
    from astroquery_ai.application.result_views import legacy_record_list
    from astroquery_ai.runtime.result_index import ResultReadIndex
    rows = [{'record_id': 'old1', 'source_id': '2007A&A...474..599P', 'field_name': 'teff',
             'field_value': 0, 'field_unit': 'K', 'entity_name': 'Betelgeuse', 'extraction_method': 'vlm_text'},
            {'record_id': 'old2', 'source_id': 'db', 'field_name': 'teff', 'field_value': 0,
             'extraction_method': 'database_query'}]
    sources = [{'source_id': '2007A&A...474..599P', 'title': 'Paper', 'year': 2007},
               {'source_id': 'db', 'source_type': 'database'}]
    quality = {'quality_report': {'report_state': {'normalization': {'modifications': [{'record_id': 'old1'}]},
               'conflict': {'verification': {'duplicate_groups': [{'record_ids': ['old1', 'old2'], 'field_name': 'teff'}]}}}}}
    indexed = ResultReadIndex(tmp_path / 'cache.sqlite3')
    def build():
        return legacy_record_list(rows, sources, quality), {'resource': 'records', 'legacy_version': 1,
            'source_labels': {s['source_id']: s for s in sources}}
    result = indexed.read(('legacy', 'archive-hash'), build, filters={'quick': 'modified', 'q': 'VLM 文本'})
    assert result['total'] == 1 and result['items'][0]['record_id'] == 'old1'
    assert result['items'][0]['flags']['duplicate']
    assert result['items'][0]['duplicate_group']['anchor_id'] == 'old2'
    assert indexed.read(('legacy', 'archive-hash'), build, filters={'source_group': 'database'})['items'][0]['record_id'] == 'old2'
    assert indexed.read(('legacy', 'archive-hash'), build, filters={'q': '有效温度'})['total'] == 2


def test_analysis_projection_preserves_exact_coordinates_and_independent_errors(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 6)
    body['revision'] = 2
    body['derived'] = [{'measurement_id': 'm00000', 'derived_id': 'd0', 'main_state': 'ready',
        'status': 'ready', 'value_typed': {'kind': 'real', 'value': '1.234567890123456789'},
        'limit': 'upper', 'coordinate_units': {'main': 'K'},
        'uncertainty_typed': {'components': [{'status': 'identity',
            'output_component': {'kind': 'asymmetric_delta', 'values': {'minus': '0.0123', 'plus': '0.0456'},
                                 'role': 'sys', 'level': None}}]}}]
    with repo.transaction() as conn:
        diff = repo.put_object(conn, tid, 'difference', 'diff', 1, {'comparison_projection': {'groups': [
            {'group_id': 'g', 'property_id': 'p-temperature', 'meaning': 'saved grouping', 'measurement_ids': ['m00000']}]}})
        body['difference'] = {'report_ref': diff}
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    result = page(repo, service, tid, projection='analysis', limit=1)
    item = result['items'][0]
    assert result['total'] == 6 and result['delivery_revision'] == 2
    assert item['source']['uncertainty'] == body['measurements'][0]['uncertainty']
    assert item['derived']['uncertainty_typed'] == body['derived'][0]['uncertainty_typed']
    assert item['derived']['value_typed']['value'] == '1.234567890123456789'
    assert item['derived']['limit'] == 'upper'
    assert item['comparison_groups'] == [{'group_id': 'g', 'property_id': 'p-temperature', 'meaning': 'saved grouping'}]
    assert 'evidence_refs' not in item['source'] and 'context' not in item and 'archive_groups' not in item
    assert page(repo, service, tid, limit=1)['items'][0]['source']['uncertainty'] != item['source']['uncertainty']


def test_legacy_route_reads_original_saved_archive_and_warm_page_without_reparse(tmp_path, monkeypatch):
    import sqlite3
    from fastapi.testclient import TestClient
    from astroquery_ai.api.http import create_app
    from tests.rebuild.test_legacy_history import make_database
    source = tmp_path / 'legacy.db'
    make_database(source)
    rows = [{'record_id': f'old{i}', 'source_id': 's1', 'field_name': 'teff', 'field_value': str(i)} for i in range(3)]
    with sqlite3.connect(source) as conn:
        state = {'final_output': {'records': rows, 'sources': [{'source_id': 's1', 'title': 'Old paper'}]}}
        conn.execute('UPDATE tasks SET state_json=?', (canonical(state).decode(),))
    app = create_app(tmp_path / 'runtime', start_worker=False)
    application = app.state.application
    tid = application.legacy.import_database(source)['imported_task_ids'][0]
    with TestClient(app) as client:
        delivery_id = client.get(f'/api/tasks/{tid}/delivery').json()['delivery_id']
        base = f'/api/tasks/{tid}/deliveries/{delivery_id}/records'
        assert [r['record_id'] for r in client.get(base).json()['items']] == ['old0', 'old1', 'old2']
        first = client.get(base + '?view=list&limit=1&q=有效温度')
        assert first.status_code == 200 and first.json()['total'] == 3
        assert first.json()['legacy_version'] == 1 and 'snapshot_ref' not in first.json()
        def forbidden(*args, **kwargs):
            raise AssertionError('warm legacy page must not parse archived state')
        monkeypatch.setattr(application.legacy, 'resource', forbidden)
        assert client.get(base + '?view=list&limit=1&offset=2&q=有效温度').json()['items'][0]['record_id'] == 'old2'


def test_display_search_keeps_null_fallbacks_limits_and_log_coordinate_labels():
    from astroquery_ai.application.result_filters import record_coordinates, value_text
    row = {'source': {'measurement_id': 'm', 'source_ref': {'id': 's'}, 'limit': 'upper'},
        'property_binding': {'property_id': 'p', 'definition': {'name_cn': 'Ratio'},
            'output_profile': {'unit': {'kind': 'dimensionless', 'canonical_symbol': None},
                               'representation': {'kind': 'log10'}}},
        'derived': {'main_state': 'ready', 'value_typed': {'kind': 'category', 'raw_label': None, 'code': 'A'}, 'limit': None}}
    value = record_coordinates(row)
    assert value['field_value'] == '上限 A'
    assert value['field_unit'] == 'log10（无量纲原生坐标）'
    assert value_text({'kind': 'real', 'value': None}) == '未记录'


def test_export_resolves_filters_from_authoritative_snapshot_not_disposable_cache(tmp_path):
    import sqlite3
    repo, service, tid, _ = setup_delivery(tmp_path, 3)
    page(repo, service, tid)
    with sqlite3.connect(tmp_path / 'cache' / 'ui-read-models.sqlite3') as conn:
        conn.execute("UPDATE rows SET source_id='wrong-cache-source'")
    result = service.export(tid, {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
        'expected_delivery_revision': 1, 'format': 'json', 'export_schema_version': 1,
        'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {'source_id': 's1'}, 'excluded_measurement_ids': []}})
    assert result['selection']['selected_ids'] == ['m00000']


def test_native_paper_nested_year_controls_sort_search_and_compact_labels(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    body['revision'] = 2
    body['sources'] = [
        {'source_id': 's1', 'kind': 'paper', 'year': 2099,
         'work': {'work_id': 'old-work', 'records': [{'titles': ['Old paper'], 'year': 2001}]}},
        {'source_id': 's2', 'kind': 'paper',
         'work': {'work_id': 'new-work', 'records': [{'titles': ['New paper'], 'year': 2025}]}},
        {'source_id': 's3', 'kind': 'paper', 'year': 2010,
         'work': {'work_id': 'fallback-work', 'records': [{'titles': ['Fallback paper'], 'year': None}]}},
    ]
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'delivery', 'delivery', 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(ref).decode())
    result = page(repo, service, tid, filters={'year_sort': 'desc'})
    assert [r['source']['measurement_id'] for r in result['items']] == ['m00001', 'm00002', 'm00000']
    assert [r['source_label']['year'] for r in result['items']] == [2025, 2010, 2001]
    assert [r['source']['measurement_id'] for r in page(repo, service, tid, filters={'q': '2025'})['items']] == ['m00001']
    assert page(repo, service, tid, filters={'q': '2099'})['total'] == 0
    with repo.read() as conn:
        sources = service.read_page(conn, tid, 'delivery', 'sources', filters={'q': '2025'})
    assert sources['total'] == 1 and sources['items'][0]['year'] == 2025
    exported = service.export(tid, {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
        'expected_delivery_revision': 2, 'format': 'json', 'export_schema_version': 1,
        'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {'q': '2025'}, 'excluded_measurement_ids': []}})
    assert exported['selection']['selected_ids'] == ['m00001']


@pytest.mark.parametrize(('nested', 'expected'), [(0, 0), ('', ''), (False, False), (None, 2099), (2001, 2001)])
def test_compact_paper_year_uses_nullish_not_truthy_precedence(nested, expected):
    from astroquery_ai.application.result_views import source_list
    source = {'source_id': 'paper', 'year': 2099, 'work': {'records': [{'year': nested}]}}
    assert source_list({'sources': [source]})[0]['year'] == expected
