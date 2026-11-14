"""Persistent category contracts against isolated overlays, including hidden entries."""
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore


@pytest.fixture
def store(tmp_path):
    result = UserKnowledgeStore(resource_dir=tmp_path / 'resources', data_dir=tmp_path / 'data')
    result.base_entries = [
        {'id': 'base-a', 'title': 'Alpha', 'category': 'physical_laws', 'description': 'Original',
         'properties': [], 'is_user': False, 'is_override': False},
        {'id': 'base-b', 'title': 'Beta', 'category': 'reference_limits', 'description': 'Original',
         'properties': [], 'is_user': False, 'is_override': False},
    ]
    result.base_entries_by_id = {entry['id']: entry for entry in result.base_entries}
    return result


def test_empty_category_survives_restart_and_appears_in_summary_and_graph(store):
    created = store.create_category({'label': '星系研究'})
    category = created['category']
    assert category['id'] != '星系研究'
    assert category['label'] == '星系研究'
    assert category['is_custom'] is True
    assert (category['count'], category['entry_count'], category['revision'], created['revision']) == (0, 0, 1, 1)
    reloaded = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    for categories in (reloaded.get_categories()['items'], reloaded.get_summary()['categories'],
                       reloaded.get_graph(view='overview')['categories']):
        assert next(item for item in categories if item['id'] == category['id'])['label'] == '星系研究'


def test_rename_preserves_stable_id_entry_revision_and_scientific_content(store):
    category = store.create_category({'label': 'Original category'})['category']
    entry = store.create_user_entry({'id': 'note', 'title': 'Note', 'category': category['id'],
                                     'description': 'Scientific content', 'sources': 'Reference'})
    renamed = store.rename_category(category['id'], {'label': 'Renamed', 'expected_revision': 1})
    assert renamed['category']['id'] == category['id']
    assert renamed['category']['revision'] == 2
    detail = store.get_detail('note')
    assert (detail['category'], detail['category_label'], detail['revision']) == (category['id'], 'Renamed', entry['revision'])
    assert (detail['description'], detail['sources']) == ('Scientific content', 'Reference')
    assert store.list_entries(view='summary')['items'][0]['category_label'] == 'Renamed'
    assert store.to_knowledge_block(detail)['category_label'] == 'Renamed'
    graph = store.get_graph(view='overview')
    assert next(node for node in graph['nodes'] if node.get('category') == category['id'])['label'] == 'Renamed'


def test_delete_moves_visible_and_hidden_records_without_changing_preferences_or_content(store):
    category = store.create_category({'label': 'Move me'})['category']
    user = store.create_user_entry({'id': 'note', 'title': 'Note', 'category': category['id'],
                                    'description': 'Keep me', 'base_id': 'base-a', 'preferred': True})
    store.update_entry('base-a', {'category': category['id'], 'description': 'Custom science', 'preferred': True})
    hidden = store.delete_entry('base-a')
    metadata = next(item for item in store.get_categories()['items'] if item['id'] == category['id'])
    assert (metadata['count'], metadata['entry_count']) == (1, 2)
    result = store.delete_category(category['id'], expected_revision=1, target_category='user_private')
    assert result['moved_count'] == 2
    assert store.get_entry('base-a') is None
    migrated = store.get_entry('note')
    assert (migrated['category'], migrated['description'], migrated['base_id'], migrated['preferred']) == (
        'user_private', 'Keep me', 'base-a', True)
    assert migrated['revision'] == user['revision'] + 1
    assert store.user_overrides['base-a']['category'] == 'user_private'
    assert store.user_overrides['base-a']['description'] == 'Custom science'
    assert store.entry_revisions['base-a'] == hidden['revision'] + 1
    assert store.preferences['base-a']['preference'] == 'preferred'
    with pytest.raises(DomainError) as stale:
        store.update_entry('note', {'category': category['id'], 'expected_revision': user['revision']})
    assert stale.value.status in {409, 422}
    with pytest.raises(DomainError) as stale_restore:
        store.restore_default('base-a', expected_revision=hidden['revision'])
    assert stale_restore.value.status == 409
    store.restore_default('base-a', expected_revision=hidden['revision'] + 1)
    assert store.get_entry('base-a')['category'] == 'physical_laws'
    assert category['id'] not in {item['id'] for item in store.get_categories()['items']}


@pytest.mark.parametrize('label', ['', ' ', 'x' * 41, 'physical_laws', 'PHYSICS', '物理定律', None, 3])
def test_invalid_and_builtin_alias_labels_do_not_write_overlay(store, label):
    with pytest.raises(DomainError) as failure:
        store.create_category({'label': label})
    assert failure.value.status in {409, 422}
    assert not store.overlay_file.exists()


def test_duplicate_labels_builtin_edits_revision_conflicts_and_invalid_destinations(store):
    category = store.create_category({'label': 'Unique'})['category']
    original = store.overlay_file.read_bytes()
    operations = [
        lambda: store.create_category({'label': 'UNIQUE'}),
        lambda: store.rename_category('physical_laws', {'label': 'No', 'expected_revision': 0}),
        lambda: store.delete_category('physical_laws', expected_revision=0),
        lambda: store.rename_category(category['id'], {'label': 'New', 'expected_revision': 0}),
        lambda: store.rename_category(category['id'], {'label': 'law', 'expected_revision': 1}),
        lambda: store.delete_category(category['id'], expected_revision=0),
        lambda: store.delete_category(category['id'], expected_revision=1, target_category='missing'),
        lambda: store.delete_category(category['id'], expected_revision=1, target_category=category['id']),
    ]
    for operation in operations:
        with pytest.raises(DomainError):
            operation()
        assert store.overlay_file.read_bytes() == original
    with pytest.raises(DomainError) as conflict:
        store.rename_category(category['id'], {'label': 'New', 'expected_revision': 0})
    assert conflict.value.status == 409


@pytest.mark.parametrize('operation', ['create', 'rename', 'delete'])
def test_category_failed_atomic_save_preserves_disk_and_memory(store, monkeypatch, operation):
    category = store.create_category({'label': 'Original'})['category']
    store.create_user_entry({'id': 'note', 'title': 'Note', 'category': category['id']})
    original = store.overlay_file.read_bytes()
    def no_replace(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr('os.replace', no_replace)
    with pytest.raises(DomainError) as failure:
        if operation == 'create':
            store.create_category({'label': 'Unsaved'})
        elif operation == 'rename':
            store.rename_category(category['id'], {'label': 'Unsaved', 'expected_revision': 1})
        else:
            store.delete_category(category['id'], expected_revision=1)
    assert failure.value.status == 503
    assert store.overlay_file.read_bytes() == original
    assert next(item for item in store.get_categories()['items'] if item['id'] == category['id'])['label'] == 'Original'
    assert store.get_entry('note')['category'] == category['id']
    assert store.get_entry('note')['revision'] == 1


def test_legacy_names_are_inferred_preserved_when_empty_and_deleted_names_do_not_resurrect(store):
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.overlay_file.write_text(json.dumps({'user_entries': {
        'old': {'id': 'old', 'title': 'Old', 'category': 'Legacy notes', 'description': 'Old science'}},
        'deleted_ids': [], 'overrides': {}}), encoding='utf-8')
    legacy = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    category = next(item for item in legacy.get_categories()['items'] if item['id'] == 'Legacy notes')
    assert (category['label'], category['revision']) == ('Legacy notes', 0)
    legacy.update_entry('old', {'category': 'user_private', 'expected_revision': 0})
    restarted = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert next(item for item in restarted.get_categories()['items'] if item['id'] == 'Legacy notes')['count'] == 0
    restarted.delete_category('Legacy notes', expected_revision=0)
    with pytest.raises(DomainError):
        restarted.update_entry('old', {'category': 'Legacy notes'})
    with pytest.raises(DomainError):
        restarted.create_user_entry({'title': 'Stale category', 'category': 'custom_00000000000000000000000000000000'})
    assert restarted.get_entry('old')['description'] == 'Old science'


def test_category_http_routes_are_registered_before_generic_entry_routes(tmp_path):
    app = create_app(root=tmp_path / 'app', start_worker=False, allow_synthetic=True)
    client = TestClient(app)
    categories = client.get('/api/knowledge/categories')
    assert categories.status_code == 200, categories.text
    builtin = next(item for item in categories.json()['items'] if item['id'] == 'physical_laws')
    assert builtin['is_custom'] is False and builtin['revision'] == 0
    created = client.post('/api/knowledge/categories', json={'label': 'HTTP category'})
    assert created.status_code == 200, created.text
    category = created.json()['category']
    renamed = client.put('/api/knowledge/categories/' + category['id'], json={'label': 'Renamed', 'expected_revision': 1})
    assert renamed.status_code == 200, renamed.text
    assert client.put('/api/knowledge/categories/' + category['id'], json={'label': 'Stale', 'expected_revision': 1}).status_code == 409
    deleted = client.delete('/api/knowledge/categories/' + category['id'], params={'expected_revision': 2, 'target_category': 'user_private'})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()['moved_count'] == 0
    assert client.put('/api/knowledge/categories/physical_laws', json={'label': 'No', 'expected_revision': 0}).status_code in {403, 422}


def test_legacy_category_ids_with_slashes_remain_editable_and_accept_revision_zero(tmp_path):
    app = create_app(root=tmp_path / 'app', start_worker=False, allow_synthetic=True)
    store = app.state.application.user_knowledge
    store.create_user_entry({'id': 'legacy', 'title': 'Old note', 'category': 'Star/Galaxy notes'})
    client = TestClient(app)
    url = '/api/knowledge/categories/' + quote('Star/Galaxy notes', safe='')
    renamed = client.put(url, json={'label': 'Renamed legacy', 'expected_revision': 0})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['category']['id'] == 'Star/Galaxy notes'
    deleted = client.delete(url, params={'expected_revision': 1})
    assert deleted.status_code == 200, deleted.text
    assert store.get_entry('legacy')['category'] == 'user_private'


@pytest.mark.parametrize('override_elsewhere', [False, True])
def test_restore_of_legacy_base_cannot_resurrect_deleted_category_or_destination(store, override_elsewhere):
    store.base_entries[0]['category'] = 'Legacy base category'
    destination = store.create_category({'label': 'Destination'})['category']
    if override_elsewhere:
        store.update_entry('base-a', {'category': 'reference_limits', 'description': 'Override'})
    store.delete_category('Legacy base category', expected_revision=0, target_category=destination['id'])
    store.restore_default('base-a')
    entry = store.get_entry('base-a')
    assert (entry['category'], entry['description']) == (destination['id'], 'Original')
    store.delete_category(destination['id'], expected_revision=1, target_category='user_private')
    store.restore_default('base-a')
    assert store.get_entry('base-a')['category'] == 'user_private'
    assert store.base_entries[0]['category'] == 'Legacy base category'
    assert not any(item['id'] in {'Legacy base category', destination['id']} for item in store.get_summary()['categories'])


def test_new_bare_category_labels_obey_length_limit_while_existing_legacy_names_work(store):
    with pytest.raises(DomainError) as invalid:
        store.create_user_entry({'title': 'New entry', 'category': 'x' * 41})
    assert invalid.value.status == 422
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.overlay_file.write_text(json.dumps({'user_entries': {
        'old': {'id': 'old', 'title': 'Legacy entry', 'category': 'x' * 41}}}), encoding='utf-8')
    legacy = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    assert legacy.update_entry('old', {'category': 'x' * 41, 'title': 'Updated'})['category'] == 'x' * 41


def test_renamed_legacy_category_does_not_reserve_its_old_label(store):
    store.create_user_entry({'id': 'note', 'title': 'Legacy note', 'category': 'Reusable name'})
    store.rename_category('Reusable name', {'label': 'Renamed legacy', 'expected_revision': 0})
    created = store.create_category({'label': 'Reusable name'})['category']
    assert created['id'] != 'Reusable name'
    assert store.get_entry('note')['category_label'] == 'Renamed legacy'


def test_category_colors_are_canonical_persistent_and_preserve_scientific_revisions(store):
    category = store.create_category({'label': 'Tinted', 'color': '#A1B2C3'})['category']
    assert category['color'] == '#a1b2c3'
    entry = store.create_user_entry({'id': 'tinted-note', 'title': 'Science', 'category': category['id']})
    custom = store.rename_category(category['id'], {'color': '#DDEEFF', 'expected_revision': 1})['category']
    builtin = store.rename_category('physical_laws', {'color': '#ABCDEF', 'expected_revision': 0})['category']
    assert (custom['color'], custom['revision'], builtin['color'], builtin['revision']) == ('#ddeeff', 2, '#abcdef', 1)
    assert builtin['label'] == '物理定律' and builtin['is_custom'] is False
    assert store.get_entry('tinted-note')['revision'] == entry['revision']
    assert store.get_entry('base-a')['revision'] == 0
    restarted = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    for categories in (restarted.get_categories()['items'], restarted.get_summary()['categories'],
                       restarted.get_graph(view='overview')['categories']):
        colors = {item['id']: (item['color'], item['revision']) for item in categories}
        assert colors[category['id']] == ('#ddeeff', 2)
        assert colors['physical_laws'] == ('#abcdef', 1)
    with pytest.raises(DomainError) as failure:
        store.rename_category('physical_laws', {'color': '#112233', 'expected_revision': 0})
    assert failure.value.status == 409


@pytest.mark.parametrize('color', [None, '', '#fff', 'ffffff', '#12345g', '#12345678', 'red', 3, '#123456\n'])
def test_invalid_category_colors_do_not_write_or_change_memory(store, color):
    category = store.create_category({'label': 'Original'})['category']
    before = store.get_categories()
    original = store.overlay_file.read_bytes()
    for operation in (
        lambda: store.create_category({'label': 'Invalid', 'color': color}),
        lambda: store.rename_category(category['id'], {'color': color, 'expected_revision': 1}),
        lambda: store.rename_category('physical_laws', {'color': color, 'expected_revision': 0}),
    ):
        with pytest.raises(DomainError) as failure:
            operation()
        assert failure.value.status == 422
        assert store.get_categories() == before
        assert store.overlay_file.read_bytes() == original


def test_builtin_color_update_cannot_smuggle_label_or_unlock_deletion(store):
    store.rename_category('physical_laws', {'color': '#123456', 'expected_revision': 0})
    before = store.overlay_file.read_bytes()
    for payload in ({'label': 'Changed'}, {'label': '物理定律', 'color': '#abcdef'}):
        with pytest.raises(DomainError) as failure:
            store.rename_category('physical_laws', {**payload, 'expected_revision': 1})
        assert failure.value.status == 422
    with pytest.raises(DomainError) as failure:
        store.delete_category('physical_laws', expected_revision=1)
    assert failure.value.status == 422
    assert store.overlay_file.read_bytes() == before


def test_category_order_is_shared_by_summary_graph_and_restart_including_empty_categories(store):
    category = store.create_category({'label': 'Empty', 'color': '#ABCDEF'})['category']
    store.rename_category('reference_limits', {'color': '#FEDCBA', 'expected_revision': 0})
    before = store.get_categories()
    ids = [item['id'] for item in reversed(before['items'])]
    result = store.reorder_categories({'ids': ids, 'expected_revision': before['revision']})
    assert result['success'] is True and result['revision'] == before['revision'] + 1
    assert [item['id'] for item in result['items']] == ids
    assert [item['order'] for item in result['items']] == list(range(len(ids)))
    assert {item['id']: item['revision'] for item in result['items']} == {
        item['id']: item['revision'] for item in before['items']}
    for reader in (store, UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)):
        for categories in (reader.get_categories()['items'], reader.get_summary(keyword='no match')['categories'],
                           reader.get_graph(view='overview', keyword='no match')['categories']):
            assert [item['id'] for item in categories] == ids
            assert [item['order'] for item in categories] == list(range(len(ids)))
            assert next(item for item in categories if item['id'] == category['id'])['color'] == '#abcdef'
    graph = store.get_graph(view='overview')
    assert [node['category'] for node in graph['nodes'] if node['kind'] == 'category'] == ['reference_limits', 'physical_laws']
    assert [node['order'] for node in graph['nodes'] if node['kind'] == 'category'] == [3, 7]
    assert next(node for node in graph['nodes'] if node.get('category') == 'reference_limits')['color'] == '#fedcba'


@pytest.mark.parametrize('case', ['duplicate', 'missing', 'extra', 'not-list', 'not-string', 'stale', 'missing-revision', 'bool-revision'])
def test_reorder_rejects_invalid_membership_and_library_revision_without_writing(store, case):
    store.create_category({'label': 'Original'})
    before = store.get_categories()
    original = store.overlay_file.read_bytes()
    ids = [item['id'] for item in before['items']]
    payload = {'ids': ids, 'expected_revision': before['revision']}
    if case == 'duplicate':
        payload['ids'] = [ids[0], *ids[:-1]]
    elif case == 'missing':
        payload['ids'] = ids[:-1]
    elif case == 'extra':
        payload['ids'] = [*ids, 'unknown']
    elif case == 'not-list':
        payload['ids'] = 'physical_laws'
    elif case == 'not-string':
        payload['ids'] = [*ids[:-1], {}]
    elif case == 'stale':
        payload['expected_revision'] -= 1
    elif case == 'missing-revision':
        del payload['expected_revision']
    else:
        payload['expected_revision'] = True
    with pytest.raises(DomainError) as failure:
        store.reorder_categories(payload)
    assert failure.value.status == (409 if case == 'stale' else 422)
    assert store.get_categories() == before
    assert store.overlay_file.read_bytes() == original


def test_order_refreshes_cross_instance_and_detects_membership_drift(store):
    second = UserKnowledgeStore(resource_dir=store.resource_dir, data_dir=store.data_dir)
    second.base_entries = store.base_entries
    second.base_entries_by_id = store.base_entries_by_id
    before = second.get_categories()
    ids = [item['id'] for item in before['items']]
    added = store.create_category({'label': 'Concurrent'})['category']
    with pytest.raises(DomainError) as stale:
        second.reorder_categories({'ids': ids, 'expected_revision': before['revision']})
    assert stale.value.status == 409
    fresh = second.get_categories()
    with pytest.raises(DomainError) as missing:
        second.reorder_categories({'ids': ids, 'expected_revision': fresh['revision']})
    assert missing.value.status == 422
    reordered = second.reorder_categories({'ids': [added['id'], *ids], 'expected_revision': fresh['revision']})
    assert store.get_categories()['items'] == reordered['items']
    store.rename_category('physical_laws', {'color': '#FEDCBA', 'expected_revision': 0})
    assert next(item for item in second.get_categories()['items'] if item['id'] == 'physical_laws')['color'] == '#fedcba'


def test_order_legacy_fallback_create_append_delete_remove_and_new_inference(store):
    store.create_user_entry({'id': 'z', 'title': 'Z', 'category': 'Z legacy'})
    store.create_user_entry({'id': 'a', 'title': 'A', 'category': 'A legacy'})
    raw = json.loads(store.overlay_file.read_text(encoding='utf-8'))
    raw.pop('category_order', None)
    store.overlay_file.write_text(json.dumps(raw), encoding='utf-8')
    before = store.get_categories()
    assert [item['id'] for item in before['items']][-2:] == ['A legacy', 'Z legacy']
    ids = [item['id'] for item in reversed(before['items'])]
    store.reorder_categories({'ids': ids, 'expected_revision': before['revision']})
    added = store.create_category({'label': 'Appended'})['category']
    assert [item['id'] for item in store.get_categories()['items']] == [*ids, added['id']]
    store.delete_category('Z legacy', expected_revision=0)
    ids.remove('Z legacy')
    assert [item['id'] for item in store.get_categories()['items']] == [*ids, added['id']]
    store.create_user_entry({'id': 'new', 'title': 'New', 'category': 'New inferred'})
    assert [item['id'] for item in store.get_categories()['items']] == [*ids, added['id'], 'New inferred']


@pytest.mark.parametrize('operation', ['builtin-color', 'custom-color', 'reorder'])
def test_appearance_atomic_save_failure_rolls_back_disk_memory_and_revisions(store, monkeypatch, operation):
    custom = store.create_category({'label': 'Original'})['category']
    before = store.get_categories()
    original = store.overlay_file.read_bytes()
    def unavailable(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr('os.replace', unavailable)
    with pytest.raises(DomainError) as failure:
        if operation == 'reorder':
            store.reorder_categories({'ids': [item['id'] for item in reversed(before['items'])],
                                      'expected_revision': before['revision']})
        else:
            store.rename_category('physical_laws' if operation == 'builtin-color' else custom['id'],
                                  {'color': '#123456', 'expected_revision': 0 if operation == 'builtin-color' else 1})
    assert failure.value.status == 503
    assert store.get_categories() == before
    assert store.overlay_file.read_bytes() == original


def test_color_and_order_http_contract(tmp_path):
    app = create_app(root=tmp_path / 'app', start_worker=False, allow_synthetic=True)
    client = TestClient(app)
    created = client.post('/api/knowledge/categories', json={'label': 'Colored', 'color': '#ABCDEF'})
    assert created.status_code == 200
    assert created.json()['category']['color'] == '#abcdef'
    colored = client.put('/api/knowledge/categories/physical_laws', json={'color': '#123456', 'expected_revision': 0})
    assert colored.status_code == 200, colored.text
    before = client.get('/api/knowledge/categories').json()
    ids = [item['id'] for item in reversed(before['items'])]
    result = client.post('/api/knowledge/categories/order', json={'ids': ids, 'expected_revision': before['revision']})
    assert result.status_code == 200, result.text
    assert [item['id'] for item in result.json()['items']] == ids
    assert client.post('/api/knowledge/categories/order', json={'ids': ids, 'expected_revision': before['revision']}).status_code == 409
    assert client.post('/api/knowledge/categories/order', json={'ids': ids[:-1], 'expected_revision': result.json()['revision']}).status_code == 422
