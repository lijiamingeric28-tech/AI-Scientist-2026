"""Atomic detail relation edits use isolated overlays and directed links."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore


@pytest.fixture
def store(tmp_path):
    result = UserKnowledgeStore(resource_dir=tmp_path / 'resources', data_dir=tmp_path / 'data')
    result.preferences = {}
    result.base_entries = [
        {'id': 'base-a', 'title': 'Alpha', 'category': 'physical_laws', 'properties': [],
         'description': 'Original reviewed content', 'is_user': False, 'is_override': False,
         'review_metadata': {'reviewer': 'retained'}},
        {'id': 'base-b', 'title': 'Beta', 'category': 'reference_limits', 'properties': [],
         'is_user': False, 'is_override': False},
    ]
    result.base_entries_by_id = {entry['id']: entry for entry in result.base_entries}
    result.base_entries_by_id['alias-a'] = result.base_entries[0]
    return result


def request_for(store, entry_id, related_ids, unlink_incoming_ids=()):
    detail = store.get_detail(entry_id)
    return {'related_ids': related_ids, 'unlink_incoming_ids': list(unlink_incoming_ids),
            'expected_revision': detail['revision'], 'expected_library_revision': detail['library_revision']}


def links(store, entry_id):
    return [(item['id'], item['direction']) for item in store.get_detail(entry_id)['relations']['related']]


def test_outgoing_add_remove_returns_fresh_detail_and_graph_without_reversing_incoming(store):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    source = store.create_user_entry({'id': 'source', 'title': 'Source', 'related_ids': ['target']})
    before = store.revision
    added = store.update_relations('target', request_for(store, 'target', [' alias-a ', 'base-a']))
    assert added['success'] is True and added['id'] == 'target'
    assert added['affected_ids'] == ['target']
    assert (added['revision'], added['library_revision']) == (2, before + 1)
    assert added['entry'] == store.get_detail('target')
    assert added['entry']['related_ids'] == ['base-a']
    assert links(store, 'target') == [('base-a', 'outgoing'), ('source', 'incoming')]
    assert store.get_entry('source')['revision'] == source['revision']
    assert store.get_entry('source')['related_ids'] == ['target']
    graph = store.get_graph(view='focus', focus_id='target')
    assert {(edge['source'], edge['target']) for edge in graph['edges'] if edge['relation_type'] == 'user_link'} == {
        ('target', 'base-a'), ('source', 'target')}
    removed = store.update_relations('target', request_for(store, 'target', []))
    assert removed['entry']['related_ids'] == []
    assert links(store, 'target') == [('source', 'incoming')]
    assert [(edge['source'], edge['target']) for edge in store.get_graph(view='focus', focus_id='target')['edges']
            if edge['relation_type'] == 'user_link'] == [('source', 'target')]


@pytest.mark.parametrize('keep_outgoing', [False, True])
def test_unlinking_both_directions_updates_each_changed_entry_once(store, keep_outgoing):
    store.create_user_entry({'id': 'target', 'title': 'Target', 'related_ids': ['base-b']})
    store.create_user_entry({'id': 'source', 'title': 'Source', 'related_ids': ['target', 'base-a']})
    store.update_entry('target', {'related_ids': ['base-b', 'source']})
    before = store.revision
    outgoing = ['base-b', 'source'] if keep_outgoing else ['base-b']
    result = store.update_relations('target', request_for(store, 'target', outgoing, ['source', 'source']))
    assert result['affected_ids'] == (['source'] if keep_outgoing else ['target', 'source'])
    assert result['library_revision'] == before + 1
    assert result['revision'] == (2 if keep_outgoing else 3)
    assert store.get_entry('source')['revision'] == 2
    assert store.get_entry('source')['related_ids'] == ['base-a']
    assert result['entry'] == store.get_detail('target')
    assert links(store, 'target') == ([('base-b', 'outgoing'), ('source', 'outgoing')]
                                       if keep_outgoing else [('base-b', 'outgoing')])


def test_incoming_only_removal_leaves_target_revision_and_other_source_links_intact(store):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    store.create_user_entry({'id': 'source', 'title': 'Source', 'related_ids': ['base-a', 'target', 'base-b']})
    result = store.update_relations('target', request_for(store, 'target', [], ['source']))
    assert result['affected_ids'] == ['source']
    assert result['revision'] == 1
    assert result['entry']['library_revision'] == 3
    assert store.get_entry('source')['related_ids'] == ['base-a', 'base-b']
    assert result['entry']['relations']['related'] == []


def test_noop_does_not_create_an_override_or_touch_disk_and_library(store):
    before = store.get_detail('base-a')
    result = store.update_relations('alias-a', {'related_ids': [], 'expected_revision': 0,
                                                'expected_library_revision': 0})
    assert result == {'success': True, 'id': 'base-a', 'entry': before, 'revision': 0,
                      'library_revision': 0, 'affected_ids': []}
    assert not store.overlay_file.exists()
    store.create_user_entry({'id': 'target', 'title': 'Target', 'related_ids': ['base-a']})
    original = store.overlay_file.read_bytes()
    unchanged = store.update_relations('target', request_for(store, 'target', ['alias-a', 'base-a']))
    assert unchanged['affected_ids'] == []
    assert unchanged['revision'] == 1 and unchanged['library_revision'] == 1
    assert store.overlay_file.read_bytes() == original


@pytest.mark.parametrize('invalid', [
    None, [], {}, {'related_ids': []}, {'expected_revision': 0, 'expected_library_revision': 0},
    {'related_ids': None}, {'related_ids': 'base-a'}, {'related_ids': [3]}, {'related_ids': [' ']},
    {'related_ids': ['base-a'] * 101}, {'related_ids': ['target']}, {'related_ids': ['missing']},
    {'unlink_incoming_ids': None}, {'unlink_incoming_ids': 'source'}, {'unlink_incoming_ids': [False]},
    {'unlink_incoming_ids': ['']},
    {'expected_revision': None}, {'expected_revision': True}, {'expected_revision': -1},
    {'expected_library_revision': None}, {'expected_library_revision': True}, {'expected_library_revision': -1},
    {'expected_library_revision': '1'}, {'title': 'Unintended edit'},
])
def test_invalid_relation_payload_never_writes(store, invalid):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    payload = request_for(store, 'target', [])
    if isinstance(invalid, dict) and invalid not in ({}, {'related_ids': []},
            {'expected_revision': 0, 'expected_library_revision': 0}):
        payload.update(invalid)
    else:
        payload = invalid
    original = store.overlay_file.read_bytes()
    before = store._state()
    with pytest.raises(DomainError) as failure:
        store.update_relations('target', payload)
    assert failure.value.status == 422
    assert store._state() == before
    assert store.overlay_file.read_bytes() == original


@pytest.mark.parametrize('source_id', ['base-a', 'missing', 'target', 'hidden-source'])
def test_unlink_must_identify_an_actual_visible_incoming_edge(store, source_id):
    store.create_user_entry({'id': 'target', 'title': 'Target', 'related_ids': ['base-a']})
    store.create_user_entry({'id': 'hidden-source', 'title': 'Hidden', 'related_ids': ['target']})
    store.delete_entry('hidden-source')
    original = store.overlay_file.read_bytes()
    with pytest.raises(DomainError) as failure:
        store.update_relations('target', request_for(store, 'target', [], [source_id]))
    assert failure.value.status == 422
    assert store.overlay_file.read_bytes() == original
    assert store.get_entry('target')['related_ids'] == ['base-a']


def test_existing_unavailable_outgoing_can_be_retained_or_removed_but_not_newly_added(store):
    store.create_user_entry({'id': 'target', 'title': 'Target', 'related_ids': ['base-a']})
    store.delete_entry('base-a')
    result = store.update_relations('target', request_for(store, 'target', ['alias-a', 'base-b']))
    assert result['entry']['relations']['related'][0]['unavailable'] is True
    assert result['entry']['related_ids'] == ['base-a', 'base-b']
    store.update_relations('target', request_for(store, 'target', []))
    before = store.overlay_file.read_bytes()
    with pytest.raises(DomainError) as failure:
        store.update_relations('target', request_for(store, 'target', ['base-a']))
    assert failure.value.status == 422
    assert store.overlay_file.read_bytes() == before


@pytest.mark.parametrize('change', ['target', 'incoming-content', 'new-incoming', 'unrelated'])
def test_both_revisions_strictly_guard_concurrent_changes_across_store_instances(store, change):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    store.create_user_entry({'id': 'source', 'title': 'Source', 'related_ids': ['target']})
    stale = request_for(store, 'target', ['base-a'], ['source'])
    second = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    if change == 'target':
        second.update_entry('target', {'title': 'Concurrent target'})
        stale['expected_library_revision'] = second.revision
    elif change == 'incoming-content':
        second.update_entry('source', {'title': 'Concurrent source'})
    elif change == 'new-incoming':
        second.create_user_entry({'id': 'new-source', 'title': 'New source', 'related_ids': ['target']})
    else:
        second.create_user_entry({'id': 'unrelated', 'title': 'Unrelated'})
    original = store.overlay_file.read_bytes()
    with pytest.raises(DomainError) as failure:
        store.update_relations('target', stale)
    assert failure.value.status == 409
    assert store.overlay_file.read_bytes() == original
    assert store.get_entry('source')['related_ids'] == ['target']
    assert store.get_entry('target')['related_ids'] == []


def test_simultaneous_edits_with_same_snapshot_allow_only_one_commit(store):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    snapshots = [request_for(store, 'target', ['base-a']), request_for(store, 'target', ['base-b'])]
    def edit(payload):
        try:
            return store.update_relations('target', payload)
        except DomainError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, snapshots))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert 409 in results
    assert store.revision == 2
    assert store.get_entry('target')['revision'] == 2


def test_failed_multi_entry_save_rolls_back_every_entry_revision_and_disk(store, monkeypatch):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    store.create_user_entry({'id': 'source', 'title': 'Source', 'related_ids': ['target', 'base-b']})
    before = store._state()
    original = store.overlay_file.read_bytes()
    def fail_replace(*_):
        raise OSError('disk unavailable')
    monkeypatch.setattr('os.replace', fail_replace)
    with pytest.raises(DomainError) as failure:
        store.update_relations('target', request_for(store, 'target', ['base-a'], ['source']))
    assert failure.value.status == 503
    assert store._state() == before
    assert store.overlay_file.read_bytes() == original
    assert links(store, 'target') == [('source', 'incoming')]
    assert not list(store.data_dir.glob('*.tmp'))


def test_relation_edits_preserve_metadata_preferences_derivation_and_reload(store):
    category = store.create_category({'label': 'Research notes', 'color': '#123456'})['category']
    store.create_user_entry({'id': 'target', 'title': 'Target', 'description': 'Full content ' * 100,
        'formula': 'a=b', 'conditions': ['condition'], 'parameters': [{'symbol': 'x', 'unit': 'm'}],
        'properties': ['mass'], 'entity_types': ['star'], 'tags': ['tag'], 'sources': 'Citation',
        'category': category['id'], 'base_id': 'base-b', 'preference': 'deprioritized', 'weight_boost': .3})
    store.update_entry('base-a', {'related_ids': ['target', 'base-b']})
    store.set_preference('base-a', 'preferred', weight_boost=3.5)
    base = deepcopy(store.base_entries)
    before = store._state()
    target_before = store.get_detail('target')
    result = store.update_relations('target', request_for(store, 'target', ['base-b'], ['alias-a']))
    assert result['entry']['description'] == ('Full content ' * 100).strip()
    for key in ('title', 'description', 'formula', 'conditions', 'parameters', 'properties', 'entity_types',
                'tags', 'sources', 'category', 'category_label', 'base_id', 'preference', 'preferred', 'weight_boost'):
        assert result['entry'][key] == target_before[key]
    assert store.base_entries == base
    after = store._state()
    for key in ('preferences', 'cleared_preferences', 'custom_categories', 'deleted_category_ids',
                'category_redirects', 'category_appearance', 'category_order', 'deleted_ids'):
        assert after[key] == before[key]
    assert store.get_entry('base-a')['related_ids'] == ['base-b']
    assert store.get_entry('base-a')['review_metadata'] == {'reviewer': 'retained'}
    restarted = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    restarted.base_entries = deepcopy(base)
    restarted.base_entries_by_id = {entry['id']: entry for entry in restarted.base_entries}
    assert restarted.get_detail('target') == result['entry']
    assert restarted.get_entry('base-a')['related_ids'] == ['base-b']
    assert restarted.get_entry('base-a')['weight_boost'] == 3.5


def test_incoming_removal_from_reviewed_builtin_creates_only_user_override(store):
    store.base_entries[0]['related_ids'] = ['base-b']
    base = deepcopy(store.base_entries)
    result = store.update_relations('base-b', request_for(store, 'base-b', [], ['alias-a']))
    assert result['affected_ids'] == ['base-a']
    assert result['revision'] == 0 and result['library_revision'] == 1
    source = store.get_entry('base-a')
    assert source['is_override'] is True and source['base_id'] == 'base-a'
    assert source['related_ids'] == [] and source['revision'] == 1
    assert source['review_metadata'] == {'reviewer': 'retained'}
    assert store.base_entries == base


def test_all_incoming_sources_can_be_unlinked_when_indegree_exceeds_outgoing_limit(store):
    sources = [dict(store.base_entries[0], id=f'incoming-{index}', related_ids=['base-b']) for index in range(101)]
    store.base_entries.extend(sources)
    store.base_entries_by_id.update({entry['id']: entry for entry in sources})
    result = store.update_relations('base-b', request_for(store, 'base-b', [], [entry['id'] for entry in sources]))
    assert len(result['affected_ids']) == 101
    assert result['revision'] == 0 and result['library_revision'] == 1
    assert result['entry']['relations']['related'] == []
    assert all(store.get_entry(entry['id'])['revision'] == 1 for entry in sources)
    assert all(entry['related_ids'] == ['base-b'] for entry in sources)


def test_relation_route_returns_full_detail_and_validates_json_ids_and_revisions(tmp_path):
    client = TestClient(create_app(root=tmp_path / 'app', start_worker=False, allow_synthetic=True))
    client.post('/api/knowledge', json={'id': 'target', 'title': 'Target', 'description': 'Long ' * 100})
    source = client.post('/api/knowledge', json={'id': 'source', 'title': 'Source', 'related_ids': ['target']}).json()
    detail = client.get('/api/knowledge/target').json()
    payload = {'related_ids': ['source'], 'unlink_incoming_ids': ['source'],
               'expected_revision': detail['revision'], 'expected_library_revision': detail['library_revision']}
    response = client.put('/api/knowledge/target/relations', json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['affected_ids'] == ['target', 'source']
    assert result['entry'] == client.get('/api/knowledge/target').json()
    assert result['entry']['description'] == ('Long ' * 100).strip()
    assert result['entry']['relations']['related'][0]['direction'] == 'outgoing'
    assert client.get('/api/knowledge/source').json()['revision'] == source['revision'] + 1
    assert client.put('/api/knowledge/target/relations', json=payload).status_code == 409
    fresh = {**payload, 'expected_revision': result['revision'],
             'expected_library_revision': result['library_revision']}
    for invalid in ([], None, {}, {'related_ids': [], 'expected_revision': 2},
                    {**fresh, 'related_ids': ['target']}, {**fresh, 'expected_revision': True}):
        response = client.put('/api/knowledge/target/relations', json=invalid)
        assert response.status_code == 422, response.text
    assert client.put('/api/knowledge/target/relations', content='{',
                      headers={'content-type': 'application/json'}).status_code == 422
    assert client.put('/api/knowledge/missing/relations', json={
        'related_ids': [], 'expected_revision': 0, 'expected_library_revision': result['library_revision']
    }).status_code == 404
