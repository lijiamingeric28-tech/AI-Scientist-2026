"""Cross-feature regression contracts for the local/upstream backend fusion."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science import material_summaries
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore
from tests.rebuild.test_result_read_index import setup_delivery
from tests.rebuild.test_author_insight_generation import setup_case
from tests.rebuild.test_presentation_read_cache import committed_clock


def test_previous_publication_exact_id_is_readable_in_index_but_not_exportable(tmp_path):
    repo, service, tid, previous = setup_delivery(tmp_path, 3)
    latest = deepcopy(previous)
    latest.update(delivery_id='new-publication', measurements=previous['measurements'][:1])
    with repo.transaction() as conn:
        reference = repo.put_object(conn, tid, 'delivery', latest['delivery_id'], 1, latest)
        repo.mutate_task(conn, tid, delivery_ref=canonical(reference).decode())
    with repo.read() as conn:
        assert service.read_for_display(conn, tid, 'delivery', 1, allow_published=True) == previous
        for projection in ('list', 'analysis'):
            result = service.read_page(conn, tid, 'delivery', 'records', revision=1,
                                       expected_revision=1, projection=projection)
            assert result['total'] == 3
            assert result['delivery_id'] == 'delivery' and result['delivery_revision'] == 1
        with pytest.raises(DomainError) as stale:
            service.read_page(conn, tid, 'delivery', 'records', revision=1, expected_revision=2)
        assert stale.value.code == 'DELIVERY_CHANGED'
    with pytest.raises(DomainError) as historical_export:
        service.export(tid, {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
            'expected_delivery_revision': 1, 'format': 'json', 'export_schema_version': 1,
            'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {},
                          'excluded_measurement_ids': []}})
    assert historical_export.value.code == 'DELIVERY_CHANGED'


def summary_case(tmp_path):
    body, spec, release = setup_case()
    pid = body['definitions'][0]['property_id']
    spec['knowledge_release'] = {'id': 'synthetic-author', 'content_sha256': 'release'}
    card = release['author']['entries'][0]
    card['blocks'][0].update(role='definition', source_ids=['original-source'])
    release['sources'] = {'original-source': {'source_id': 'original-source', 'title': 'Original author source'}}
    store = UserKnowledgeStore(resource_dir=tmp_path/'empty', data_dir=tmp_path/'data')
    store.base_entries = [{'id': 'meaning', 'title': 'Original meaning', 'properties': [pid],
                          'description': 'Original definition', 'category': 'physical_laws', 'is_user': False}]
    store.base_entries_by_id = {entry['id']: entry for entry in store.base_entries}
    service = SimpleNamespace(app=SimpleNamespace(user_knowledge=store,
                               knowledge=SimpleNamespace(load=lambda ref: deepcopy(release))))
    return service, body, spec, store, pid


def test_material_summary_honors_suppression_and_relevant_user_preference(tmp_path):
    service, body, spec, store, pid = summary_case(tmp_path)
    before = deepcopy(body)
    original = material_summaries._knowledge(service, body, spec)[pid][0]
    assert original['sources'][0]['source_id'] == 'original-source'
    store.delete_entry('meaning')
    store.create_user_entry({'id': 'preferred', 'title': 'Preferred custom definition',
        'description': 'Custom interpretation background', 'properties': [pid], 'preferred': True})
    store.create_user_entry({'id': 'unrelated', 'title': 'Irrelevant preferred theory',
        'description': 'Must not enter this property', 'properties': ['unrelated_property'],
        'preferred': True, 'weight_boost': 10})
    knowledge = material_summaries._knowledge(service, body, spec)[pid]
    assert knowledge[0]['entry_id'] == 'preferred'
    assert knowledge[0]['user_preferred'] is True
    assert not {'meaning', 'unrelated'}.intersection(entry['entry_id'] for entry in knowledge)
    assert body == before



def test_material_summary_preserves_released_sources_and_excludes_conditional_user_theory(tmp_path):
    service, body, spec, store, pid = summary_case(tmp_path)
    store.set_preference('meaning', 'preferred', 2)
    store.create_user_entry({'id': 'conditional', 'title': 'Only for calibrated geometry',
        'properties': [pid], 'conditions': ['requires calibrated geometry'], 'preferred': True,
        'weight_boost': 20})
    knowledge = material_summaries._knowledge(service, body, spec)[pid]
    assert knowledge[0]['entry_id'] == 'meaning'
    assert knowledge[0]['sources'][0]['source_id'] == 'original-source'
    assert knowledge[0]['release_ref'] == spec['knowledge_release']
    assert knowledge[0]['user_preferred'] is True
    assert 'conditional' not in [entry['entry_id'] for entry in knowledge]


def native_delivery(tmp_path):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    body = deepcopy(body)
    body.update(revision=2, status='completed', evidence_views=[])
    body['sources'][0].update(kind='official_attachment',
        association={'source_table_id': 'original/table'}, year=None,
        work={'records': [{'year': 2014}]})
    body['evidence_index'] = [{'evidence_id': 'e1', 'source_id': 's1', 'text_origin': 'original_cells',
        'locator': {'table': 'original/table', 'row': 17, 'column': 'temperature'},
        'raw_text': canonical({'cells': {'MJD': '56679.4377', 'Filt': 'UVW2'},
            'columns': [{'name': 'MJD', 'unit_text': 'd', 'description': 'Modified Julian Date', 'ucd': 'time.epoch'},
                        {'name': 'Filt', 'description': 'Original filter', 'ucd': 'instr.filter'}]}).decode()}]
    body['contexts'] = [{'context_id': 'c', 'measurement_ref': {'id': 'm00000'}, 'conditions': []}]
    body['provenance_bundle'].update(interpretations=[{'interpretation_id': 'i1'}], human_answers=[])
    quality = {'quality_report': {'report_state': {'normalization': {
        'modifications': [{'record_id': 'm00000'}]}}}}
    with repo.transaction() as conn:
        body['quality'] = {'report_ref': repo.put_object(conn, tid, 'quality', 'q', 1, quality)}
        body['difference'] = {'report_ref': repo.put_object(conn, tid, 'difference', 'd', 1, {})}
        reference = repo.put_object(conn, tid, 'delivery', body['delivery_id'], 2, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(reference).decode())
    return repo, service, tid, body, quality


def result_client(repo, service):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from astroquery_ai.api.routes.results import register
    app = FastAPI()
    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(error.as_dict(), status_code=error.status)
    register(app, SimpleNamespace(repository=repo, delivery=service,
        legacy=SimpleNamespace(get=lambda *_: None), history=SimpleNamespace(source=lambda conn, tid: service.delivery_reference(conn, tid)[0])), None)
    return TestClient(app)


def test_native_material_records_share_indexed_flags_coordinates_and_export_scope(tmp_path):
    from astroquery_ai.science.results import workbench_export
    repo, service, tid, body, quality = native_delivery(tmp_path)
    with result_client(repo, service) as client:
        base = f'/api/tasks/{tid}/deliveries/delivery'
        page = client.get(base+'/records', params={'view': 'list', 'quick': 'modified', 'limit': 1}).json()
        material = client.get(base+'/material_records', params={'material_id': 's1',
            'property_id': 'p-temperature', 'limit': 1}).json()
        assert page['total'] == material['total'] == 1
        assert material['items'][0] == page['items'][0]
        row = page['items'][0]
        assert row['source_label']['year'] == 2014
        assert row['source_label']['association']['source_table_id'] == 'original/table'
        assert row['native_coordinates']['epochs'][0]['value'] == '56679.4377'
        assert row['native_coordinates']['bands'][0]['value'] == 'UVW2'
        analysis = client.get(base+'/records', params={'view': 'analysis', 'quick': 'modified'}).json()['items'][0]
        assert analysis['source']['uncertainty'] == body['measurements'][0]['uncertainty']
        assert analysis['native_coordinates'] == row['native_coordinates']
        detail = client.get(base+'/records', params={'record_id': 'm00000', 'view': 'summary'}).json()['items'][0]
        assert detail['source'] == body['measurements'][0]
    exported = service.export(tid, {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
        'expected_delivery_revision': 2, 'format': 'json', 'export_schema_version': 2,
        'selection': {'mode': 'filtered', 'filter_version': 1, 'filters': {'quick': 'modified'},
                      'excluded_measurement_ids': []}})
    assert exported['selection']['selected_ids'] == ['m00000']
    request = {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': 'delivery',
        'expected_delivery_revision': 2, 'export_schema_version': 3,
        'selection': {'measurement_ids': ['m00000'], 'figure_ids': []},
        'options': {'data_format': 'csv', 'group_by': 'material', 'container': 'zip', 'include_originals': False}}
    preview = workbench_export.preview(service, tid, request)
    assert preview['record_count'] == 1
    values = dict(zip(preview['data_preview']['columns'], preview['data_preview']['rows'][0]))
    assert values['measurement_id'] == 'm00000'
    assert values['native_epoch'] == '56679.4377'
    assert values['native_band'] == 'UVW2'
    assert (values['error_minus'], values['error_plus'], values['error_unit']) == ('56', '61', 'K')


def test_old_projection_cache_is_rebuilt_with_native_coordinates(tmp_path, monkeypatch):
    from astroquery_ai.application import result_views
    from astroquery_ai.runtime import result_index
    repo, service, tid, body, quality = native_delivery(tmp_path)
    project = result_views.record_list
    actual_protocol = result_index.PROJECTION_PROTOCOL
    def legacy_projection(*args, **kwargs):
        rows = project(*args, **kwargs)
        for row in rows:
            row.pop('native_coordinates', None)
        return rows
    monkeypatch.setattr(result_index, 'PROJECTION_PROTOCOL', 'delivery-list/3')
    monkeypatch.setattr(result_views, 'record_list', legacy_projection)
    with repo.read() as conn:
        old = service.read_page(conn, tid, 'delivery', 'records', limit=1)
        assert 'native_coordinates' not in old['items'][0]
    monkeypatch.setattr(result_index, 'PROJECTION_PROTOCOL', actual_protocol)
    monkeypatch.setattr(result_views, 'record_list', project)
    with repo.read() as conn:
        fresh = service.read_page(conn, tid, 'delivery', 'records', limit=1)
    assert fresh['items'][0]['native_coordinates']['bands'][0]['value'] == 'UVW2'


@pytest.mark.parametrize('release_mode', ['missing', 'without_author'])
def test_custom_material_summary_background_does_not_require_legacy_author_package(tmp_path, release_mode):
    service, body, spec, store, pid = summary_case(tmp_path)
    store.create_user_entry({'id': 'custom', 'title': 'Custom property definition',
        'description': 'Locally curated explanation', 'properties': [pid], 'preferred': True})
    if release_mode == 'missing':
        spec.pop('knowledge_release')
    else:
        service.app.knowledge.load = lambda ref: {'sources': {}}
    assert material_summaries._knowledge(service, body, spec)[pid][0]['entry_id'] == 'custom'


@pytest.mark.parametrize('future_id', ['delivery', 'new-publication'])
def test_replay_explicit_display_cannot_read_later_publication(tmp_path, future_id):
    repo, service, tid, body = setup_delivery(tmp_path, 3)
    replay = repo.create_task('SYNTHETIC historical replay', kind='replay')['task_id']
    with repo.transaction() as conn:
        _, captured = service.delivery_reference(conn, tid)
        repo.put_object(conn, replay, 'replay_snapshot', replay, 1, {'source_delivery_ref': captured})
        conn.execute('INSERT INTO replay_sources VALUES(?,?,?)', (replay, tid, '{}'))
        future = deepcopy(body)
        future.update(delivery_id=future_id, revision=2 if future_id == 'delivery' else 1)
        reference = repo.put_object(conn, tid, 'delivery', future_id, future['revision'], future)
        repo.mutate_task(conn, tid, delivery_ref=canonical(reference).decode())
    with repo.read() as conn:
        assert service.read_for_display(conn, replay, 'delivery', 1, allow_published=True) == body
        for read in (
            lambda: service.read_for_display(conn, replay, future_id, future['revision'], allow_published=True),
            lambda: service.read_page(conn, replay, future_id, 'records', revision=future['revision']),
        ):
            with pytest.raises(DomainError) as error:
                read()
            assert error.value.code == 'DELIVERY_CHANGED'


def test_replay_material_summary_does_not_borrow_post_capture_generation(tmp_path):
    from astroquery_ai.runtime.codec import utcnow
    repo, service, tid, body, _ = native_delivery(tmp_path)
    replay = repo.create_task('SYNTHETIC material replay', kind='replay')['task_id']
    with repo.transaction() as conn:
        _, reference = service.delivery_reference(conn, tid)
        repo.put_object(conn, replay, 'replay_snapshot', replay, 1,
            {'source_delivery_ref': reference, 'created_at': utcnow()})
        conn.execute('INSERT INTO replay_sources VALUES(?,?,?)', (replay, tid, '{}'))
    summary_id = material_summaries._identity(body, 's1', 'p-temperature')
    with repo.transaction() as conn:
        repo.put_object(conn, tid, 'material_summary', summary_id, 1,
            {'state': 'ready', 'text': 'Generated after the replay was captured'})
    with result_client(repo, service) as client:
        params = {'view': 'workbench', 'material_id': 's1', 'property_id': 'p-temperature',
                  'delivery_revision': 2}
        live = client.get(f'/api/tasks/{tid}/deliveries/delivery/materials', params=params).json()
        saved = client.get(f'/api/tasks/{replay}/deliveries/delivery/materials', params=params).json()
        assert live['items'][0]['summary']['state'] == 'ready'
        assert saved['items'][0]['summary']['state'] == 'unavailable'


def test_historical_frame_keeps_summary_generated_before_frame_on_older_revision(tmp_path, committed_clock):
    repo, service, tid, body, _ = native_delivery(tmp_path)
    with repo.transaction() as conn:
        _, reference = service.delivery_reference(conn, tid)
        published = repo.event(conn, tid, 'delivery_ready', {'delivery_ref': reference})
        summary_id = material_summaries._identity(body, 's1', 'p-temperature')
        repo.put_object(conn, tid, 'material_summary', summary_id, 1,
            {'state': 'ready', 'text': 'Available at this historical frame'})
        frame = repo.event(conn, tid, 'material_summary_updated', {})
        later = deepcopy(body)
        later['revision'] = 3
        reference = repo.put_object(conn, tid, 'delivery', 'delivery', 3, later)
        repo.mutate_task(conn, tid, delivery_ref=canonical(reference).decode())
        repo.event(conn, tid, 'delivery_ready', {'delivery_ref': reference})
    with result_client(repo, service) as client:
        params = {'view': 'workbench', 'material_id': 's1', 'property_id': 'p-temperature',
                  'delivery_revision': 2}
        url = f'/api/tasks/{tid}/deliveries/delivery/materials'
        earlier = client.get(url, params={**params, 'at_seq': published['seq']}).json()
        later = client.get(url, params={**params, 'at_seq': frame['seq']}).json()
        assert earlier['items'][0]['summary']['state'] == 'unavailable'
        assert later['items'][0]['summary']['state'] == 'ready'


def test_replay_revision_choices_stop_at_capture_but_live_history_keeps_all_revisions(tmp_path, committed_clock):
    from astroquery_ai.runtime.codec import utcnow
    repo, service, tid, body, _ = native_delivery(tmp_path)
    body = deepcopy(body)
    body.update(delivery_id='metadata-publication', counts={'records': 3, 'sources': 3})
    replay = repo.create_task('SYNTHETIC captured publication choices', kind='replay')['task_id']
    with repo.transaction() as conn:
        for revision in (1, 2, 3):
            body['revision'] = revision
            captured = repo.put_object(conn, tid, 'delivery', body['delivery_id'], revision, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(captured).decode())
        repo.put_object(conn, replay, 'replay_snapshot', replay, 1,
            {'schema_version': 'ReplaySnapshot/1', 'source_task_id': tid,
             'source_delivery_ref': captured, 'created_at': utcnow()})
        conn.execute('INSERT INTO replay_sources VALUES(?,?,?)', (replay, tid, '{}'))
    with repo.transaction() as conn:
        body['revision'] = 4
        latest = repo.put_object(conn, tid, 'delivery', body['delivery_id'], 4, body)
        repo.mutate_task(conn, tid, delivery_ref=canonical(latest).decode())
    with result_client(repo, service) as client:
        replay_url = f'/api/tasks/{replay}/delivery'
        response = client.get(replay_url)
        assert response.status_code == 200
        assert response.json()['revision'] == 3
        assert response.json()['available_revisions'] == [1, 2, 3]
        historical = {'delivery_id': body['delivery_id'], 'delivery_revision': 1}
        replay_past = client.get(replay_url, params=historical).json()
        assert replay_past['revision'] == 1 and replay_past['available_revisions'] == [1, 2, 3]
        live_past = client.get(f'/api/tasks/{tid}/delivery', params=historical).json()
        assert live_past['revision'] == 1 and live_past['available_revisions'] == [1, 2, 3, 4]
        assert client.get(replay_url, params={**historical, 'delivery_revision': 4}).status_code == 409


@pytest.mark.parametrize('record_terminal_event', [True, False])
def test_real_replay_api_presentation_execution_and_clock_keep_captured_history(
        tmp_path, committed_clock, record_terminal_event):
    from fastapi.testclient import TestClient
    from astroquery_ai.api.http import create_app
    from astroquery_ai.application.presentation import presentation
    api = create_app(tmp_path / 'history-runtime', start_worker=False)
    app = api.state.application
    tid = app.create('SYNTHETIC captured title', str(uuid4()))['task_id']
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, tid, lifecycle='cancelled')
        app.repository.event(conn, tid, 'task_state_changed' if record_terminal_event else 'archive_saved',
                             {'lifecycle': 'cancelled'} if record_terminal_event else {})
    replay = app.history.replay(tid, 1, str(uuid4()))['task_id']
    with app.repository.read() as conn:
        capture = app.repository.object(conn, replay, 'replay_snapshot', replay)
    horizon = capture['source_view']['core_event_cursor']
    # Use the real registered API without entering lifespan/recovery or starting workers.
    client = TestClient(api)
    base = f'/api/tasks/{replay}'
    initial = client.get(base + '/presentation').json()
    initial_execution = client.get(base + '/execution', params={'section': 'overview'}).json()
    initial_clock = client.get(base + '/replay-clock').json()
    assert initial['cursor'] == horizon and initial['counts']['sources'] == 0
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, tid, 'source', 'future-source', 1, {'source_id': 'future-source'})
        # Simulate source recovery/import after capture; public terminal controls
        # deliberately forbid restarting this synthetic cancelled fixture.
        conn.execute("UPDATE tasks SET title=?, lifecycle='running' WHERE task_id=?",
                     ('SYNTHETIC future title', tid))
        future = app.repository.event(conn, tid, 'task_state_changed', {'lifecycle': 'running'})
        app.repository.event(conn, tid, 'execution_stage_changed', {'stage_id': 'extraction'})
    # Warm cached and cold reconstruction must agree at the captured horizon.
    assert client.get(base + '/presentation').json() == initial
    app.__dict__.pop('_presentation_read_cache', None)
    assert client.get(base + '/presentation').json() == initial
    assert client.get(base + '/execution', params={'section': 'overview'}).json() == initial_execution
    assert client.get(base + '/replay-clock').json() == initial_clock
    assert initial['lifecycle'] == initial_execution['lifecycle'] == 'cancelled'
    assert initial_execution['title'] == 'SYNTHETIC captured title'
    for endpoint, extra in [('presentation', {}), ('execution', {}), ('execution', {'section': 'overview'})]:
        allowed = client.get(base + '/' + endpoint, params={'at_seq': horizon, **extra})
        assert allowed.status_code == 200 and allowed.json()['cursor'] == horizon
        denied = client.get(base + '/' + endpoint, params={'at_seq': future['seq'], **extra})
        assert denied.status_code == 422 and denied.json()['detail']['code'] == 'RESYNC_REQUIRED'
    past = client.get(base + '/presentation', params={'at_seq': 1}).json()
    assert past['cursor'] == 1 and past['counts']['sources'] == 0
    live = client.get(f'/api/tasks/{tid}/presentation').json()
    assert live['cursor'] > horizon and live['counts']['sources'] == 1 and live['lifecycle'] == 'running'
    live_execution = client.get(f'/api/tasks/{tid}/execution', params={'section': 'overview'}).json()
    assert live_execution['title'] == 'SYNTHETIC future title'
    assert client.get(base + '/presentation').json() == initial
    # Two replay captures of one source at different horizons must not share a projection.
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, tid, lifecycle='cancelled')
        app.repository.event(conn, tid, 'task_state_changed', {'lifecycle': 'cancelled'})
    second_replay = app.history.replay(tid, 1, str(uuid4()))['task_id']
    assert presentation(app, second_replay)['counts']['sources'] == 1
    assert presentation(app, replay) == initial
