"""Projection boundaries and conditional reads use isolated scientific packages."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from astroquery_ai.api.routes import knowledge, registry_workbench
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_registry_workbench import bench
from tests.rebuild.test_knowledge_workbench import store


@pytest.fixture
def client(bench, store):
    app = FastAPI()
    application = SimpleNamespace(registry_workbench=bench, user_knowledge=store)
    registry_workbench.register(app, application)
    knowledge.register(app, application, None)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({'detail': error.as_dict()}, status_code=error.status)

    return TestClient(app)


def test_registry_stats_keep_counts_without_constructing_editor_capabilities(bench, monkeypatch):
    full = bench.summary()

    def no_editor_data(release):
        pytest.fail('stats/directory must not construct the capability catalog')

    monkeypatch.setattr(bench, '_capabilities', no_editor_data)
    stats = bench.summary(projection='stats')
    assert stats['counts'] == {'types': 2, 'properties': 1, 'bindings': 2, 'disabled': 0, 'changed': 0}
    assert stats == {k: v for k, v in full.items() if k not in {'types', 'families', 'capabilities'}}
    directory = bench.summary(projection='directory', keyword='no match')
    assert directory['counts']['properties'] == 0
    assert len(directory['types']) == 2 and len(directory['families']) == 1
    assert 'capabilities' not in directory


def test_knowledge_stats_omit_properties_and_directory_keeps_complete_options(store):
    stats = store.get_summary(projection='stats', category='physical_laws')
    assert stats['matched_total'] == 1 and stats['total'] == 2
    assert 'properties' not in stats
    directory = store.get_summary(projection='directory', category='physical_laws')
    assert {p['id'] for p in directory['properties']} == {'effective_temperature', 'mass'}
    assert directory['matched_total'] == 1
    assert store.get_summary() == store.get_summary(projection='full')


@pytest.mark.parametrize('path', ['/registry-workbench/summary', '/knowledge/summary',
                                  '/registry-workbench/workspaces', '/registry-workbench/releases'])
def test_invalid_projection_is_rejected(client, path):
    assert client.get('/api' + path, params={'projection': 'unknown'}).status_code == 422


def test_workspace_directory_preserves_identity_but_omits_mutation_payloads(bench, client):
    workspace = bench.create_workspace()['workspace']
    bench.write(workspace['id'], 'types', {'label': 'New type', 'parent_id': '*'}, expected_revision=1)
    full = client.get('/api/registry-workbench/workspaces').json()['items'][0]
    item = client.get('/api/registry-workbench/workspaces?projection=directory').json()['items'][0]
    assert full['operations'] and full['revision'] == item['revision'] == 2
    assert item['id'] == workspace['id'] and item['base_bundle'] == workspace['base_bundle']
    assert not {'operations', 'validation', 'execution_manifest'}.intersection(item)
    assert item['updated_at'] == full['updated_at']


def test_release_directory_omits_nested_execution_data_but_keeps_exact_refs(bench, client):
    workspace = bench.create_workspace()['workspace']
    validation = bench.validate(workspace['id'], expected_revision=1)['validation']
    bench.publish(workspace['id'], expected_revision=1, validation_id=validation['id'],
                  expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='publish-test')
    full = client.get('/api/registry-workbench/releases').json()
    directory = client.get('/api/registry-workbench/releases?projection=directory').json()
    assert directory['total'] == full['total']
    assert {(i['id'], i['release_id']) for i in directory['items']} == {(i['id'], i['release_id']) for i in full['items']}
    assert directory['items'][0]['registry_ref'] == full['items'][0]['registry_ref']
    assert directory['items'][0]['knowledge_ref'] == full['items'][0]['knowledge_ref']
    published = next(i for i in directory['items'] if i['registry_ref']['id'] != workspace['base_bundle']['registry_ref']['id'])
    original = next(i for i in full['items'] if i['id'] == published['id'])
    assert published['capability_ref'] == original['capability_ref']
    assert published['base_bundle_id'] == workspace['base_bundle']['id']


@pytest.mark.parametrize('path', ['/registry-workbench/summary?projection=directory',
                                  '/knowledge/summary?projection=directory',
                                  '/registry-workbench/workspaces?projection=directory',
                                  '/registry-workbench/releases?projection=directory'])
def test_projected_get_supports_conditional_etag(client, path):
    first = client.get('/api' + path)
    assert first.status_code == 200 and first.headers.get('etag')
    unchanged = client.get('/api' + path, headers={'If-None-Match': first.headers['etag']})
    assert unchanged.status_code == 304 and unchanged.content == b''
    assert unchanged.headers['etag'] == first.headers['etag']


def test_etag_changes_with_filter_projection_and_library_revision(client, store):
    path = '/api/knowledge/summary?projection=directory'
    first = client.get(path)
    etag = first.headers.get('etag')
    assert etag
    assert client.get(path + '&keyword=Alpha', headers={'If-None-Match': etag}).status_code == 200
    assert client.get('/api/knowledge/summary?projection=stats', headers={'If-None-Match': etag}).status_code == 200
    store.create_user_entry({'id': 'new', 'title': 'New'})
    changed = client.get(path, headers={'If-None-Match': etag})
    assert changed.status_code == 200 and changed.json()['revision'] == 1
    assert changed.headers['etag'] != etag


def test_conditional_registry_read_still_validates_underlying_scope(client, bench):
    workspace = bench.create_workspace()['workspace']
    path = '/api/registry-workbench/summary?projection=directory&workspace_id=' + workspace['id']
    first = client.get(path)
    assert first.headers.get('etag')
    bench.write(workspace['id'], 'types', {'label': 'New', 'parent_id': '*'}, expected_revision=1)
    assert client.get(path, headers={'If-None-Match': first.headers['etag']}).status_code == 200
    with bench.repository.transaction() as conn:
        conn.execute('DELETE FROM registry_workspaces WHERE workspace_id=?', (workspace['id'],))
    assert client.get(path, headers={'If-None-Match': first.headers['etag']}).status_code == 404


def test_default_full_summary_remains_compatible(client, bench):
    response = client.get('/api/registry-workbench/summary')
    assert response.json() == bench.summary()
    assert 'etag' not in response.headers


def test_knowledge_summary_selects_fields_before_copying_heavy_entry_data(store):
    class DetailOnly:
        def __deepcopy__(self, memo):
            pytest.fail('summary copied detail-only entry data')

    store.base_entries[0]['parameters'] = [DetailOnly()]
    assert store.get_summary(projection='stats')['matched_total'] == 2
    assert len(store.get_summary(projection='directory')['properties']) == 2


def test_stats_do_not_construct_property_option_directory(store, monkeypatch):
    def no_option_label(info):
        pytest.fail('stats constructed the property option directory')

    monkeypatch.setattr(store, '_property_label', no_option_label)
    assert store.get_summary(projection='stats')['total'] == 2


def test_etag_matches_lists_and_strong_form_and_remains_projection_specific(client):
    path = '/api/knowledge/summary?projection=stats'
    first = client.get(path)
    etag = first.headers['etag']
    assert client.get(path, headers={'If-None-Match': '"unrelated", ' + etag[2:]}).status_code == 304
    assert client.get(path, headers={'If-None-Match': '*'}).status_code == 304
    assert client.get('/api/knowledge/summary?projection=directory', headers={'If-None-Match': etag}).status_code == 200


def test_workspace_directory_nested_bundle_is_metadata_only(bench):
    from astroquery_ai.runtime.codec import canonical

    workspace = bench.create_workspace()['workspace']
    workspace['base_bundle']['execution_manifest'] = {'large': 'payload'}
    with bench.repository.transaction() as conn:
        conn.execute('UPDATE registry_workspaces SET payload=? WHERE workspace_id=?',
                     (canonical(workspace), workspace['id']))
    item = bench.list_workspaces(projection='directory')['items'][0]
    assert 'execution_manifest' not in item['base_bundle']
    assert item['base_bundle']['registry_ref'] == workspace['base_bundle']['registry_ref']
