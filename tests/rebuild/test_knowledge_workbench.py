"""Workbench contracts exercised with isolated overlays and hand-built corpora."""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore


@pytest.fixture
def store(tmp_path):
    result = UserKnowledgeStore(resource_dir=tmp_path / 'empty', data_dir=tmp_path / 'data')
    result.preferences = {}
    result.base_entries = [
        {'id': 'base-a', 'title': 'Alpha', 'category': 'physical_laws',
         'properties': ['effective_temperature'], 'description': 'shared needle',
         'is_user': False, 'is_override': False},
        {'id': 'base-b', 'title': 'Beta', 'category': 'reference_limits',
         'properties': ['mass'], 'description': 'shared needle',
         'is_user': False, 'is_override': False},
    ]
    result.base_entries_by_id = {entry['id']: entry for entry in result.base_entries}
    return result


def test_failed_atomic_replace_preserves_disk_memory_and_revision(store, monkeypatch):
    original = store.create_user_entry({'id': 'u1', 'title': 'Original'})
    disk = store.overlay_file.read_bytes()
    def no_replace(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr('os.replace', no_replace)
    with pytest.raises(DomainError) as failure:
        store.update_entry('u1', {'title': 'Lost draft', 'expected_revision': original['revision']})
    assert failure.value.status == 503
    assert store.get_entry('u1')['title'] == 'Original'
    assert store.get_entry('u1')['revision'] == original['revision']
    assert store.overlay_file.read_bytes() == disk


def test_revisions_detect_stale_changes_and_survive_reload(store):
    created = store.create_user_entry({'id': 'u1', 'title': 'One'})
    assert (created['revision'], created['library_revision']) == (1, 1)
    updated = store.update_entry('u1', {'title': 'Two', 'expected_revision': 1})
    assert (updated['revision'], updated['library_revision']) == (2, 2)
    with pytest.raises(DomainError) as failure:
        store.set_preference('u1', 'preferred', expected_revision=1)
    assert failure.value.status == 409
    restored = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert restored.get_entry('u1')['revision'] == 2
    assert restored.list_entries()['revision'] == 2


def test_custom_category_saved_with_entry_survives_reload_and_is_available_in_facets(store):
    category = '星系演化科研笔记'
    created = store.create_user_entry({'id': 'user-category-proof', 'title': '用户自建分类验证', 'category': category})
    assert created['category'] == category
    result = store.list_entries(category=category, view='summary')
    assert result['total'] == 1
    assert result['items'][0]['id'] == created['id']
    reloaded = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.overlay_file.parent)
    assert reloaded.get_detail(created['id'])['category'] == category
    facet = next(item for item in reloaded.get_summary()['categories'] if item['id'] == category)
    assert facet['label'] == category and facet['count'] == 1 and facet['is_custom']


def test_old_overlay_defaults_to_zero_revision(store):
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.overlay_file.write_text(json.dumps({'user_entries': {'old': {'id': 'old', 'title': 'Old'}}}))
    legacy = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert legacy.get_entry('old')['revision'] == 0
    assert legacy.update_entry('old', {'title': 'New', 'expected_revision': 0})['revision'] == 1


def test_delete_override_hides_base_until_explicit_restore(store):
    override = store.update_entry('base-a', {'title': 'Override', 'preferred': True})
    deleted = store.delete_entry('base-a', expected_revision=override['revision'])
    assert deleted['action'] == 'deleted'
    assert store.get_entry('base-a') is None
    assert store.list_entries()['total'] == 1
    restored = store.restore_default('base-a', expected_revision=deleted['revision'])
    assert restored['entry']['title'] == 'Alpha'
    assert not restored['entry']['preferred']
    assert not restored['entry']['is_override']
    assert 'base-a' not in store.preferences


def test_deleted_parent_preserves_derived_entry_and_reports_unavailable(store):
    parent = store.create_user_entry({'id': 'parent', 'title': 'Parent'})
    store.create_user_entry({'id': 'child', 'title': 'Child', 'base_id': 'parent'})
    store.delete_entry(parent['id'])
    detail = store.get_detail('child')
    assert detail['base_id'] == 'parent'
    assert detail['relations']['base'] is None
    assert detail['relations']['base_unavailable'] is True
    with pytest.raises(DomainError):
        store.restore_default('child')


def test_explicit_related_knowledge_is_canonical_deduplicated_persistent_and_separate_from_derivation(store):
    store.base_entries_by_id['alias-a'] = store.base_entries_by_id['base-a']
    created = store.create_user_entry({'id': 'linked', 'title': 'Linked', 'base_id': 'base-b',
                                     'related_ids': [' alias-a ', 'base-a', 'base-b']})
    assert created['related_ids'] == ['base-a', 'base-b']
    assert created['base_id'] == 'base-b' and created['properties'] == []
    detail = store.get_detail('linked')
    assert [(item['id'], item['title'], item['direction'], item['provenance'], item['relationLabel'], item['unavailable'])
            for item in detail['relations']['related']] == [
        ('base-a', 'Alpha', 'outgoing', 'entry.related_ids', '用户关联', False),
        ('base-b', 'Beta', 'outgoing', 'entry.related_ids', '用户关联', False)]
    incoming = store.get_detail('base-a')['relations']['related']
    assert [(item['id'], item['direction']) for item in incoming] == [('linked', 'incoming')]
    store.update_entry('base-a', {'related_ids': ['linked']})
    assert store.get_detail('linked')['relations']['related'][0]['direction'] == 'both'
    restarted = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert restarted.get_entry('linked')['related_ids'] == ['base-a', 'base-b']
    assert restarted.list_entries(view='summary')['items'][0]['related_ids'] == ['base-a', 'base-b']


@pytest.mark.parametrize('related_ids', [None, 'base-a', [3], [''], ['  '], ['missing'], ['self'], ['base-a'] * 101])
def test_invalid_related_ids_never_write(store, related_ids):
    with pytest.raises(DomainError) as failure:
        store.create_user_entry({'id': 'self', 'title': 'Self', 'related_ids': related_ids})
    assert failure.value.status == 422
    assert not store.overlay_file.exists()


def test_hidden_targets_are_rejected_but_existing_unavailable_links_can_be_retained_or_removed(store):
    store.create_user_entry({'id': 'linked', 'title': 'Linked', 'related_ids': ['base-a']})
    store.delete_entry('base-a')
    detail = store.get_detail('linked')
    assert detail['related_ids'] == ['base-a']
    assert detail['relations']['related'] == [{
        'id': 'base-a', 'title': '关联知识当前不可用', 'category': None, 'category_label': None,
        'direction': 'outgoing', 'provenance': 'entry.related_ids', 'relationLabel': '用户关联', 'unavailable': True}]
    assert store.update_entry('linked', {'title': 'Retained', 'related_ids': ['base-a']})['related_ids'] == ['base-a']
    before = store.overlay_file.read_bytes()
    for operation in (
        lambda: store.create_user_entry({'title': 'New', 'related_ids': ['base-a']}),
        lambda: store.update_entry('base-b', {'related_ids': ['base-a']}),
        lambda: store.update_entry('linked', {'related_ids': ['base-a', 'missing']}),
        lambda: store.update_entry('linked', {'related_ids': ['linked']}),
    ):
        with pytest.raises(DomainError) as failure:
            operation()
        assert failure.value.status == 422
        assert store.overlay_file.read_bytes() == before
    assert store.update_entry('linked', {'related_ids': []})['related_ids'] == []


def test_deleting_user_target_preserves_link_owner_without_cascading_or_fake_graph_edges(store):
    store.create_user_entry({'id': 'target', 'title': 'Target'})
    owner = store.create_user_entry({'id': 'owner', 'title': 'Owner', 'related_ids': ['target']})
    store.delete_entry('target')
    assert store.get_entry('owner')['revision'] == owner['revision']
    assert store.get_detail('owner')['relations']['related'][0]['unavailable'] is True
    assert all(edge['relation_type'] != 'user_link' for edge in store.get_graph(view='focus', focus_id='owner')['edges'])


def test_focus_graph_includes_explicit_incoming_and_outgoing_neighbors_with_no_shared_properties(store):
    store.create_user_entry({'id': 'outgoing', 'title': 'Outgoing', 'related_ids': ['base-b']})
    store.create_user_entry({'id': 'incoming', 'title': 'Incoming', 'related_ids': ['outgoing']})
    graph = store.get_graph(view='focus', focus_id='outgoing')
    assert {node['id'] for node in graph['nodes'] if node['kind'] == 'entry'} == {'outgoing', 'base-b', 'incoming'}
    assert {(edge['source'], edge['target'], edge['relation_type'], edge['label'], edge['provenance'])
            for edge in graph['edges'] if edge['relation_type'] == 'user_link'} == {
        ('outgoing', 'base-b', 'user_link', '用户关联', 'entry.related_ids'),
        ('incoming', 'outgoing', 'user_link', '用户关联', 'entry.related_ids')}
    filtered = store.get_graph(view='focus', focus_id='outgoing', category='user_private')
    assert {node['id'] for node in filtered['nodes'] if node['kind'] == 'entry'} == {'outgoing', 'incoming'}
    assert [(edge['source'], edge['target']) for edge in filtered['edges'] if edge['relation_type'] == 'user_link'] == [('incoming', 'outgoing')]
    bounded = store.get_graph(view='focus', focus_id='outgoing', limit=1)
    assert [node['id'] for node in bounded['nodes']] == ['outgoing']
    assert bounded['edges'] == []


def test_related_ids_failed_save_preserves_both_entries_and_revisions(store, monkeypatch):
    owner = store.create_user_entry({'id': 'owner', 'title': 'Owner'})
    original = store.overlay_file.read_bytes()
    def unavailable(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr('os.replace', unavailable)
    with pytest.raises(DomainError) as failure:
        store.update_entry('owner', {'related_ids': ['base-a'], 'expected_revision': owner['revision']})
    assert failure.value.status == 503
    assert store.overlay_file.read_bytes() == original
    assert store.get_entry('owner').get('related_ids', []) == []
    assert store.get_entry('owner')['revision'] == owner['revision']
    assert store.get_detail('base-a')['relations']['related'] == []


def test_related_ids_http_create_detail_and_update(tmp_path):
    client = TestClient(create_app(root=tmp_path / 'app', start_worker=False, allow_synthetic=True))
    target = client.post('/api/knowledge', json={'id': 'target', 'title': 'Target'}).json()
    created = client.post('/api/knowledge', json={'id': 'owner', 'title': 'Owner', 'related_ids': [target['id']]})
    assert created.status_code == 200
    assert created.json()['related_ids'] == ['target']
    detail = client.get('/api/knowledge/target').json()
    assert [(item['id'], item['direction']) for item in detail['relations']['related']] == [('owner', 'incoming')]
    bad = client.put('/api/knowledge/owner', json={'related_ids': ['missing'], 'expected_revision': 1})
    assert bad.status_code == 422


@pytest.mark.parametrize('payload', [
    {'title': ' '}, {'title': 'X', 'properties': 'mass'},
    {'title': 'X', 'conditions': [4]}, {'title': 'X', 'preferred': 'false'},
    {'title': 'X', 'weight_boost': float('nan')},
    {'title': 'X', 'user_preference': 'surprise'}, {'title': 'X', 'base_id': 'missing'},
    {'title': 'X', 'user_preference': []},
])
def test_invalid_writes_do_not_mutate_overlay(store, payload):
    with pytest.raises(DomainError) as failure:
        store.create_user_entry(payload)
    assert failure.value.status == 422
    assert store.list_entries()['total'] == 2
    assert not store.overlay_file.exists()


def test_duplicate_id_and_alias_deletion_are_canonical(store):
    store.create_user_entry({'id': 'u1', 'title': 'One'})
    with pytest.raises(DomainError) as failure:
        store.create_user_entry({'id': 'u1', 'title': 'Duplicate'})
    assert failure.value.status == 409
    store.base_entries_by_id['alias-a'] = store.base_entries_by_id['base-a']
    result = store.delete_entry('alias-a')
    assert result['id'] == 'base-a'
    assert store.get_entry('base-a') is None
    assert store.get_entry('alias-a') is None


def test_existing_source_prefix_lookup_preserves_raw_details_and_merged_ids(store):
    raw_research = dict(store.base_entries[0], title='Research source detail', origin='research_entry')
    store.base_entries.append(raw_research)
    store.base_entries_by_id['research_entry:base-a'] = raw_research
    assert store.list_entries()['total'] == 2
    assert store.get_entry('base-a')['title'] == 'Alpha'
    assert store.get_entry('research_entry:base-a')['title'] == 'Research source detail'
    assert store.get_entry('research_entry:base-a')['id'] == 'base-a'
    store.delete_entry('research_entry:base-a')
    assert store.get_entry('base-a') is None
    assert store.get_entry('research_entry:base-a') is None


def test_parallel_writes_do_not_lose_entries_or_revisions(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: store.create_user_entry({'id': f'u{index}', 'title': f'Item {index}'}), range(30)))
    reloaded = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert reloaded.list_entries()['total'] == 30
    assert reloaded.list_entries()['revision'] == 30


def test_separate_process_writes_serialize_revision_and_preserve_both_entries(store, tmp_path):
    start = tmp_path / 'start'
    script = '''
import json, sys, time
from pathlib import Path
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore
resource, data, ready, start, eid = map(Path, sys.argv[1:])
store = UserKnowledgeStore(resource_dir=resource, data_dir=data)
save = store._save_user_overlay
def slow_save(payload):
    time.sleep(.15)
    return save(payload)
store._save_user_overlay = slow_save
ready.write_text('ready')
while not start.exists():
    time.sleep(.01)
created = store.create_user_entry({'id': str(eid), 'title': str(eid)})
print(json.dumps({'revision': created['library_revision']}))
'''
    processes = [subprocess.Popen([sys.executable, '-c', script, str(store.resource_dir), str(store.data_dir),
                  str(tmp_path / f'ready{index}'), str(start), eid], stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True) for index, eid in enumerate(('a', 'b'))]
    try:
        deadline = time.monotonic() + 15
        while not all((tmp_path / f'ready{index}').exists() for index in range(2)):
            if time.monotonic() > deadline:
                pytest.fail('subprocess writers did not become ready')
            time.sleep(.01)
        start.write_text('go')
        outcomes = [process.communicate(timeout=15) for process in processes]
        assert all(process.returncode == 0 for process in processes), outcomes
        assert sorted(json.loads(output)['revision'] for output, _ in outcomes) == [1, 2]
        persisted = json.loads(store.overlay_file.read_text(encoding='utf-8'))
        assert set(persisted['user_entries']) == {'a', 'b'}
        assert persisted['revision'] == 2
        assert store.list_entries(source='user')['total'] == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_reads_refresh_external_commits_and_stale_updates_conflict(store):
    store.create_user_entry({'id': 'u1', 'title': 'Original'})
    script = '''
import sys
from pathlib import Path
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore
store = UserKnowledgeStore(resource_dir=Path(sys.argv[1]), data_dir=Path(sys.argv[2]))
store.update_entry('u1', {'title': 'Remote commit', 'expected_revision': 1})
'''
    subprocess.run([sys.executable, '-c', script, str(store.resource_dir), str(store.data_dir)],
                   check=True, capture_output=True, text=True, timeout=15)
    assert store.get_entry('u1')['title'] == 'Remote commit'
    assert store.get_summary()['revision'] == 2
    with pytest.raises(DomainError) as failure:
        store.update_entry('u1', {'title': 'Stale draft', 'expected_revision': 1})
    assert failure.value.status == 409
    assert store.get_entry('u1')['title'] == 'Remote commit'


def test_list_facets_share_filters_but_category_facets_ignore_category(store):
    store.create_user_entry({'id': 'u1', 'title': 'Gamma', 'category': 'physical_laws',
                             'properties': ['teff'], 'description': 'needle'})
    store.update_entry('base-b', {'description': 'needle override'})
    query = dict(keyword='needle', category='physical_laws', property_ids=['effective_temperature'])
    page = store.list_entries(**query, sort='name', limit=1, offset=1, view='summary')
    assert page['total'] == 2
    assert [item['id'] for item in page['items']] == ['u1']
    assert (page['offset'], page['limit'], page['revision']) == (1, 1, 2)
    facets = store.get_summary(keyword='needle', category='physical_laws')
    assert (facets['total'], facets['matched_total']) == (3, 2)
    counts = {item['id']: item['count'] for item in facets['categories']}
    assert counts['physical_laws'] == 2
    assert counts['reference_limits'] == 1
    assert facets['sources'] == {'builtin': 1, 'user': 1, 'override': 0}
    assert store.list_entries(source='override')['items'][0]['id'] == 'base-b'


def test_property_relations_use_verified_exact_aliases_not_substrings(store):
    store.create_user_entry({'id': 'unknown', 'title': 'Unbound', 'properties': ['temperature_guess']})
    assert [item['id'] for item in store.list_entries(property_ids=['teff'])['items']] == ['base-a']
    detail = store.get_detail('base-a')
    assert detail['relations']['properties'][0]['id'] == 'effective_temperature'
    graph = store.get_graph(view='category', property_ids=['teff'])
    assert 'unknown' not in {node['id'] for node in graph['nodes']}
    assert all(edge['relation_type'] and edge['provenance'] for edge in graph['edges'])


def test_unknown_property_binding_remains_explicitly_unreviewed(store):
    store.create_user_entry({'id': 'unbound', 'title': 'Unbound', 'properties': ['CustomMatter']})
    facet = store.get_summary(keyword='Unbound')['properties'][0]
    assert facet['id'] == 'custommatter'
    assert facet['binding_state'] == 'unreviewed'
    graph = store.get_graph(view='category', keyword='Unbound', limit=10)
    prop = next(node for node in graph['nodes'] if node['kind'] == 'property')
    assert prop['binding_state'] == 'unreviewed'


def test_summary_previews_are_bounded_but_detail_keeps_long_original(store):
    content = '星际' * 2000
    store.create_user_entry({'id': 'long', 'title': 'Long', 'description': content})
    preview = store.list_entries(keyword='Long', view='summary')['items'][0]
    assert len(preview['description']) == 300
    assert preview['description_truncated'] is True
    assert store.get_detail('long')['description'] == content


def test_ambiguous_physical_quantities_do_not_become_equivalent_aliases(store):
    store.create_user_entry({'id': 'ambiguous', 'title': 'Distinct quantities',
                             'properties': ['temperature', 'distance_modulus', 'period']})
    assert store.list_entries(property_ids=['effective_temperature'])['total'] == 1
    assert store.list_entries(property_ids=['distance'])['total'] == 0
    assert store.list_entries(property_ids=['orbital_period'])['total'] == 0
    properties = store.get_detail('ambiguous')['relations']['properties']
    assert {item['id'] for item in properties} == {'temperature', 'distance_modulus', 'period'}
    assert all(item['binding_state'] == 'unreviewed' for item in properties)


def test_overview_aggregates_real_category_property_edges_and_counts(store):
    store.create_user_entry({'id': 'u1', 'title': 'Second temperature', 'category': 'physical_laws',
                             'properties': ['teff']})
    graph = store.get_graph(view='overview', limit=8)
    properties = {node['id']: node for node in graph['nodes'] if node['kind'] == 'property'}
    assert properties['prop_teff']['count'] == 2
    relation = next(edge for edge in graph['edges'] if edge['source'] == 'category:physical_laws'
                    and edge['target'] == 'prop_teff')
    assert relation['count'] == 2
    assert relation['provenance']['source'] == 'entry.properties'
    assert graph['meta']['represented_entries'] == 3
    assert graph['meta']['truncated'] is False


def test_focus_reports_clipping_against_its_candidates_not_entire_corpus(store):
    graph = store.get_graph(view='focus', focus_id='base-a', limit=10)
    assert graph['meta']['filtered_entries'] == 2
    assert graph['meta']['matched_entries'] == 1
    assert graph['meta']['shown_entries'] == 1
    assert graph['meta']['truncated'] is False


def test_exact_concept_labels_enrich_properties_without_approving_unknown_bindings(tmp_path):
    resources = tmp_path / 'resources'
    content = resources / 'insight_kb' / 'content'
    content.mkdir(parents=True)
    (content / 'concepts.json').write_text(json.dumps([
        {'concept_id': 'astro.age', 'label_zh': '年龄', 'property_id': 'prop-stellar-age'}]), encoding='utf-8')
    store = UserKnowledgeStore(resource_dir=resources, data_dir=tmp_path / 'data')
    store.create_user_entry({'id': 'age', 'title': 'Age binding', 'properties': ['astro.age', 'astro.age_guess']})
    labels = {item['id']: item for item in store.get_summary()['properties']}
    assert labels['astro.age']['label'] == '年龄'
    assert labels['prop-stellar-age']['label'] == '年龄'
    assert labels['astro.age_guess']['label'] == 'astro.age_guess'
    assert labels['astro.age']['binding_state'] == 'unreviewed'
    assert labels['astro.age']['label_provenance'] == 'concept:astro.age'
    detail = store.get_detail('age')
    assert detail['relations']['properties'][0]['label'] == '年龄'
    graph = store.get_graph(view='overview')
    assert next(node for node in graph['nodes'] if node.get('property_id') == 'astro.age')['label'] == '年龄'


def test_pagination_reaches_all_3000_entries_without_hidden_cap(store):
    store.base_entries = [dict(store.base_entries[0], id=f'e{i:04}', title=f'Title {i:04}') for i in range(3000)]
    store.base_entries_by_id = {entry['id']: entry for entry in store.base_entries}
    page = store.list_entries(sort='name', offset=2976, limit=24, view='summary')
    assert (page['total'], len(page['items'])) == (3000, 24)
    assert page['items'][-1]['id'] == 'e2999'
    overview = store.get_graph(view='overview', limit=10)
    assert sum(node.get('count', 0) for node in overview['nodes'] if node['kind'] in {'category', 'aggregate'}) == 3000
    reached = store.get_graph(view='category', keyword='Title 2999', limit=10)
    assert 'e2999' in {node['id'] for node in reached['nodes']}


@pytest.mark.parametrize('view', ['overview', 'category', 'focus'])
def test_graph_budget_and_focus_never_escape_filters(store, view):
    for index in range(30):
        store.base_entries.append(dict(store.base_entries[0], id=f'x{index}', title=f'X {index}'))
    store.base_entries_by_id = {entry['id']: entry for entry in store.base_entries}
    graph = store.get_graph(view=view, focus_id='base-a', category='physical_laws', limit=8)
    assert len(graph['nodes']) <= 8
    assert graph['meta']['node_count'] == len(graph['nodes'])
    assert graph['meta']['matched_entries'] == 31
    assert 'base-b' not in {node['id'] for node in graph['nodes']}
    ids = {node['id'] for node in graph['nodes']}
    assert all(edge['source'] in ids and edge['target'] in ids for edge in graph['edges'])


def test_apps_isolate_overlays_and_accept_zero_revision_for_builtin(tmp_path):
    a = create_app(root=tmp_path / 'a', start_worker=False, allow_synthetic=True)
    b = create_app(root=tmp_path / 'b', start_worker=False, allow_synthetic=True)
    ca, cb = TestClient(a), TestClient(b)
    response = ca.put('/api/knowledge/law.stefan_boltzmann', json={'title': 'Only A', 'expected_revision': 0})
    assert response.status_code == 200, response.text
    assert cb.get('/api/knowledge/law.stefan_boltzmann').json()['title'] != 'Only A'
    assert a.state.application.user_knowledge.overlay_file.parent == tmp_path / 'a'
    summary = ca.get('/api/knowledge/summary?category=physical_laws').json()
    assert summary['matched_total'] > 0
    assert 'relations' in ca.get('/api/knowledge/law.stefan_boltzmann').json()
    assert ca.put('/api/knowledge/law.stefan_boltzmann', json={'title': 'Stale', 'expected_revision': 0}).status_code == 409
    assert ca.post('/api/knowledge/law.stefan_boltzmann/restore', json=[]).status_code == 422


def test_controller_and_tools_use_application_store(store):
    from astroquery_ai.agent_harness.controller import AgentController
    bundle = MagicMock()
    bundle.theories = []
    bundle.theories_by_prop = {}
    bundle.definitions_by_id = {}
    bundle.resolve_property_id.return_value = 'effective_temperature'
    store.create_user_entry({'id': 'private', 'title': 'Private app knowledge', 'preferred': True})
    application = MagicMock(user_knowledge=store)
    controller = AgentController(bundle, application)
    text = controller.tools.execute_tool('get_scientific_theory', {'property_name': '温度'})
    assert 'Private app knowledge' in text


def test_property_insight_report_uses_injected_overlay(store):
    from astroquery_ai.science.property_insights import final_report
    store.create_user_entry({'id': 'private', 'title': 'Private report knowledge',
                             'properties': ['effective_temperature'], 'preferred': True})
    delivery = {'delivery_id': 'd', 'measurements': [], 'snapshot_ref': 's',
                'task_id': 't', 'target': 'Star', 'materials_ref': 'm'}
    units = [{'property_id': 'effective_temperature', 'unit_id': 'u', 'claims': [], 'measurements': []}]
    report = final_report(delivery, {'properties': []}, {'knowledge_id': 'k'}, units, {}, knowledge_store=store)
    private = next(item for item in report['knowledge_blocks'] if item['entry_id'] == 'private')
    assert private['user_preferred'] is True
    assert private['title'] == 'Private report knowledge'


def test_agent_does_not_resurrect_hidden_entries_from_cached_theories(store):
    from astroquery_ai.agent_harness.tools import DomainTools
    bundle = MagicMock()
    bundle.theories = [{'entry_id': 'base-a', 'theory_id': 'base-a', 'title': 'Should remain hidden',
                        'claim': {'claim_id': 'kb-base-a', 'text': 'Cached base theory'}}]
    bundle.theories_by_prop = {}
    bundle.definitions_by_id = {}
    store.delete_entry('base-a')
    text = DomainTools(bundle, knowledge_store=store).execute_tool('get_scientific_theory', {'theory_id': 'base-a'})
    assert 'Should remain hidden' not in text
    assert 'Cached base theory' not in text


def test_insight_theory_blocks_use_overrides_and_hide_deleted_entries(store, monkeypatch):
    from astroquery_ai.science.property_insights import final_report
    from astroquery_ai.science.theory_knowledge import TheoryKnowledgeStore
    theory = MagicMock()
    theory.derive_network_relationships.return_value = [{'theory_id': 'base-a'}]
    theory.by_id = {'base-a': {'id': 'base-a'}}
    theory.to_knowledge_block.return_value = {'entry_id': 'base-a', 'title': 'Cached base',
                                             'claim': {'claim_id': 'kb-base-a'}}
    monkeypatch.setattr(TheoryKnowledgeStore, 'get_instance', lambda: theory)
    delivery = {'delivery_id': 'd', 'measurements': [], 'snapshot_ref': 's',
                'task_id': 't', 'target': 'Star', 'materials_ref': 'm'}
    store.update_entry('base-a', {'title': 'Active override'})
    report = final_report(delivery, {'properties': []}, {}, [], {}, knowledge_store=store)
    assert next(item for item in report['knowledge_blocks'] if item['entry_id'] == 'base-a')['title'] == 'Active override'
    store.delete_entry('base-a')
    report = final_report(delivery, {'properties': []}, {}, [], {}, knowledge_store=store)
    assert not report['cross_field_relationships']
    assert all(item['entry_id'] != 'base-a' for item in report['knowledge_blocks'])


def test_unfinished_property_reports_share_the_same_application_overlay(store):
    from astroquery_ai.science.results.publication import _unfinished_insights
    store.create_user_entry({'id': 'private', 'title': 'Application private theory', 'preferred': True})
    repository, connection = MagicMock(), MagicMock()
    repository.objects.return_value = []
    connection.execute.return_value.fetchone.return_value = [0]
    delivery = {'delivery_id': 'd', 'measurements': [], 'snapshot_ref': 's'}
    spec = {'properties': [], 'run_policy': {'insights': {'presentation': 'research-property/1'}}}
    report = _unfinished_insights(repository, connection, 'task', delivery, spec, 'user_cancelled', knowledge_store=store)
    assert report['reason'] == 'user_cancelled'
    assert next(item for item in report['knowledge_blocks'] if item['entry_id'] == 'private')['user_preferred'] is True
