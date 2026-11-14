from copy import deepcopy

import pytest

from astroquery_ai.registry.service import RegistryService
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.registry_fixture import make_release


@pytest.fixture
def bench(tmp_path):
    from astroquery_ai.registry.workbench import RegistryWorkbench
    repo = Repository(tmp_path / 'runtime.sqlite3')
    registry = RegistryService(tmp_path / 'registry', repo, allow_synthetic=True)
    make_release(tmp_path / 'source')
    registry.import_release(tmp_path / 'source')
    return RegistryWorkbench(registry, repo)


def test_projection_has_exact_properties_scoped_counts_and_graph(bench):
    summary = bench.summary()
    props = bench.list_items('properties')
    assert summary['counts']['properties'] == props['total'] == 1
    assert summary['counts']['types'] == 2
    assert props['items'][0]['id'] != props['items'][0]['property_id']
    scoped = bench.summary(type_id='*')
    assert scoped['counts']['bindings'] == 1
    graph = bench.graph(limit=80)
    assert graph['meta']['node_count'] == len(graph['nodes'])
    assert len(graph['edges']) == 2


@pytest.mark.parametrize('restriction', ['binding_status', 'type_condition', 'binding_condition'])
def test_later_publication_restores_original_qualified_scope(bench, restriction):
    from astroquery_ai.registry.workspace_release import qualification_base_ref, release_ref
    original = release_ref(bench.registry.load())
    binding = bench.list_items('bindings', type_id='*')['items'][0]
    kind, identifier = ('types', '*') if restriction == 'type_condition' else ('bindings', binding['id'])
    for payload, expected in (({'status': 'disabled'} if restriction == 'binding_status' else
            {'conditions': [{'otype': 'pA*'}]}, 0),
            ({'status': 'active'} if restriction == 'binding_status' else
             {'conditions': binding['conditions']} if restriction == 'binding_condition' else {'conditions': []}, 1)):
        workspace = bench.create_workspace()['workspace']
        bench.write(workspace['id'], kind, payload, item_id=identifier, expected_revision=1)
        validation = bench.validate(workspace['id'], expected_revision=2)['validation']
        assert validation['state'] == 'passed'
        bench.publish(workspace['id'], expected_revision=2, validation_id=validation['id'],
            expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key=workspace['id'])
        release = bench.registry.load()
        support = bench.registry.support(release, ['*'], 'synthetic-subject')
        assert len(support['bindings']) == expected
        if expected:
            assert qualification_base_ref(release, support['bindings']) == original


def test_cumulative_knowledge_compatibility_can_restore_original_exact_binding(bench):
    from astroquery_ai.registry.workspace_release import knowledge_compatibility
    _, projection = bench._base(bench.registry.active_bundle()['registry_ref'])
    binding = next(iter(projection['bindings'].values()))
    original = {'entries': {'author': {'title': 'SYNTHETIC author'}}, 'data': {'bindings': [{
        'item_id': 'author-binding', 'otype': binding['type_id'], 'definition_ref': binding['definition_ref'],
        'output_profile_ref': binding['profile_ref'], 'entry_ids': ['author']}]}}
    previous_wrapper = {'base_knowledge': original, 'entries': original['entries'], 'data': {'bindings': []}}
    compatibility = knowledge_compatibility(previous_wrapper, projection)
    assert compatibility['compatible_binding_ids'] == ['author-binding']
    assert compatibility['links'][binding['property_key']][0]['compatibility'] == 'compatible'


@pytest.mark.parametrize('cumulative', [False, True])
def test_knowledge_wrapper_respects_recorded_compatibility_policy(bench, tmp_path, cumulative):
    from types import SimpleNamespace
    from astroquery_ai.registry.workspace_release import load_workspace_knowledge, knowledge_compatibility, release_ref
    from astroquery_ai.runtime.codec import canonical, content_hash, digest
    release, projection = bench._base(bench.registry.active_bundle()['registry_ref'])
    binding = next(iter(projection['bindings'].values()))
    original = {'entries': {'author': {'title': 'SYNTHETIC author'}}, 'data': {'bindings': [{
        'item_id': 'author-binding', 'otype': binding['type_id'], 'definition_ref': binding['definition_ref'],
        'output_profile_ref': binding['profile_ref'], 'entry_ids': ['author']}]}}
    previous = {'manifest': {'release_id': 'previous-kb', 'content_sha256': 'a' * 64},
        'base_knowledge': original, 'entries': original['entries'], 'data': {'bindings': []}}
    compatibility = knowledge_compatibility(previous, projection, original_source=cumulative)
    payload = {'base_knowledge_ref': release_ref(previous),
        'compatible_binding_ids': compatibility['compatible_binding_ids'], 'gaps': compatibility['gaps']}
    if cumulative:
        payload['compatibility_policy'] = 'cumulative-exact-source/2'
    manifest = {'release_id': 'new-kb', 'registry_release_ref': release_ref(release), 'compatibility_sha256': digest(payload)}
    manifest['content_sha256'] = content_hash(manifest)
    (tmp_path / 'compatibility.json').write_bytes(canonical(payload))
    service = SimpleNamespace(load=lambda ref: previous,
        registry=SimpleNamespace(load=lambda identifier: {**release, 'workspace': {'projection': projection}}))
    loaded = load_workspace_knowledge(service, tmp_path, manifest)
    assert loaded['entries'] == original['entries']
    assert [b['item_id'] for b in loaded['data']['bindings']] == (['author-binding'] if cumulative else [])


def test_drafts_are_sparse_revisioned_and_do_not_mutate_source(bench):
    ws = bench.create_workspace()['workspace']
    first = bench.list_items('properties')['items'][0]
    changed = bench.write(ws['id'], 'properties', {'label': '我的长度'}, item_id=first['id'], expected_revision=1)
    assert changed['workspace']['revision'] == 2
    assert bench.detail('properties', first['id'])['label'] == first['label']
    local = bench.detail('properties', first['id'], workspace_id=ws['id'])
    assert local['label'] == '我的长度'
    assert local['definition_ref'] == first['definition_ref']
    assert len(bench.get_workspace(ws['id'])['operations']) == 1
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'properties', {'label': '过期'}, item_id=first['id'], expected_revision=1)
    assert exc.value.status == 409


def test_dependencies_block_type_disable_and_new_item_can_be_removed(bench):
    ws = bench.create_workspace()['workspace']
    with pytest.raises(DomainError) as exc:
        bench.delete(ws['id'], 'types', '*', expected_revision=1)
    assert exc.value.code == 'REGISTRY_DEPENDENTS'
    created = bench.write(ws['id'], 'types', {'label': '我的星', 'parent_id': '*'}, expected_revision=1)
    item = created['item']
    assert item['standard_otype'] == '*'
    assert item['id'].startswith('user_type_')
    assert bench.delete(ws['id'], 'types', item['id'], expected_revision=2)['success']
    assert bench.summary(workspace_id=ws['id'])['counts']['types'] == 2


def test_validation_invalidates_and_publication_is_atomic_idempotent_and_rollback(bench):
    original = bench.registry.active_bundle()
    ws = bench.create_workspace()['workspace']
    validation = bench.validate(ws['id'], expected_revision=1)['validation']
    assert validation['state'] == 'passed'
    result = bench.publish(ws['id'], expected_revision=1, validation_id=validation['id'],
                           expected_active_bundle_id=original['id'], idempotency_key='publish-1')
    assert result['success']
    assert bench.registry.active_bundle()['id'] == result['bundle']['id']
    assert bench.publish(ws['id'], expected_revision=1, validation_id=validation['id'],
                         expected_active_bundle_id=original['id'], idempotency_key='publish-1') == result
    loaded = bench.registry.load()
    assert loaded['manifest']['schema_version'] == 'registry-workspace/1'
    assert bench.registry.support(loaded, ['*'], 'synthetic-subject')['bindings']
    rolled = bench.activate(original['id'], expected_active_bundle_id=result['bundle']['id'], idempotency_key='rollback-1')
    assert rolled['success']
    assert bench.registry.active_bundle()['registry_ref'] == original['registry_ref']


def test_scientific_identity_change_rejected_and_unit_validation(bench):
    ws = bench.create_workspace()['workspace']
    prop = bench.list_items('properties')['items'][0]
    definition = deepcopy(prop['definition'])
    definition['quantity_key'] = 'different-quantity'
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'properties', {'definition': definition}, item_id=prop['id'], expected_revision=1)
    assert exc.value.code == 'SCIENTIFIC_IDENTITY_IMMUTABLE'
    profiles = deepcopy(prop['output_profiles'])
    profiles[0]['unit']['canonical_symbol'] = 'utterly_invalid_unit'
    bench.write(ws['id'], 'properties', {'output_profiles': profiles}, item_id=prop['id'], expected_revision=1)
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'failed'
    assert any(error['code'] == 'INVALID_UNIT' for error in validation['errors'])

def test_stale_validation_is_not_reusable_after_write(bench):
    ws = bench.create_workspace()['workspace']
    validation = bench.validate(ws['id'], expected_revision=1)['validation']
    prop = bench.list_items('properties')['items'][0]
    bench.write(ws['id'], 'properties', {'label': '修改'}, item_id=prop['id'], expected_revision=1)
    with pytest.raises(DomainError) as exc:
        bench.publish(ws['id'], expected_revision=2, validation_id=validation['id'],
                      expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='stale')
    assert exc.value.code == 'VALIDATION_REQUIRED'


def test_filesystem_publication_failure_does_not_activate_or_close_draft(bench, monkeypatch):
    from astroquery_ai.registry import workbench_publication
    bundle = bench.registry.active_bundle()
    ws = bench.create_workspace()['workspace']
    validation = bench.validate(ws['id'], expected_revision=1)['validation']
    def fail(*args):
        raise OSError('injected rename failure')
    monkeypatch.setattr(workbench_publication.os, 'replace', fail)
    with pytest.raises(DomainError) as exc:
        bench.publish(ws['id'], expected_revision=1, validation_id=validation['id'], expected_active_bundle_id=bundle['id'], idempotency_key='fail')
    assert exc.value.status == 503
    assert bench.registry.active_bundle() == bundle
    assert bench.get_workspace(ws['id'])['status'] == 'draft'


def test_user_type_choices_exact_hash_and_explicit_selection(bench):
    from astroquery_ai.registry.workspace_release import user_type_choices
    ws = bench.create_workspace()['workspace']
    created = bench.write(ws['id'], 'types', {'label': '我的星', 'parent_id': '*'}, expected_revision=1)['item']
    v = bench.validate(ws['id'], expected_revision=2)['validation']
    bench.publish(ws['id'], expected_revision=2, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='child')
    release = bench.registry.load()
    choices = user_type_choices(release, ['*'])
    assert [x['id'] for x in choices] == [created['id']]
    assert user_type_choices(release, ['pA*']) == []
    chosen = {'id': choices[0]['id'], 'version': choices[0]['revision'], 'content_sha256': choices[0]['content_sha256']}
    assert bench.registry.support(release, ['*'], 'synthetic-subject', user_type_ref=chosen)['user_type_ref'] == chosen
    chosen['content_sha256'] = '0' * 64
    with pytest.raises(DomainError) as exc:
        bench.registry.support(release, ['*'], 'synthetic-subject', user_type_ref=chosen)
    assert exc.value.code == 'USER_TYPE_STALE'


def test_new_property_has_honest_metadata_and_native_execution(bench):
    ws = bench.create_workspace()['workspace']
    prop = bench.list_items('properties')['items'][0]
    profile = deepcopy(prop['output_profiles'][0])
    for k in ('profile_id', 'version', 'content_sha256', 'property_id', 'definition_version', 'review_ref'):
        profile.pop(k, None)
    new = bench.write(ws['id'], 'properties', {'label': '用户长度', 'description': '来自用户的定义',
        'family_id': prop['family_id'], 'definition': {'quantity_key': 'user:new_length', 'quantity_kind': 'length', 'subject_class_id': 'synthetic-subject'},
        'output_profiles': [profile], 'type_ids': ['*'], 'source_note': '论文来源'}, expected_revision=1)['item']
    assert not new['automatic_conversion_ready']
    assert not new['definition'].get('review_ref')
    assert not new['output_profiles'][0].get('review_ref')
    v = bench.validate(ws['id'], expected_revision=2)['validation']
    assert v['state'] == 'passed'
    bench.publish(ws['id'], expected_revision=2, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='new-property')
    support = bench.registry.support(bench.registry.load(), ['*'], 'synthetic-subject')
    binding = next(b for b in support['bindings'] if b['property_id'] == new['property_id'])
    assert binding['execution_capabilities']['native']['ready']
    assert not binding['execution_capabilities']['normalization']['ready']


def test_official_metadata_override_still_has_official_anchor(bench):
    ws = bench.create_workspace()['workspace']
    bench.write(ws['id'], 'types', {'label': '恒星展示名'}, item_id='*', expected_revision=1)
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'passed'
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'types', {'code': 'changed'}, item_id='*', expected_revision=2)
    assert exc.value.code == 'STANDARD_TYPE_IMMUTABLE'


def test_5000_entries_are_reachable_with_stable_paging_and_graph_budget(bench):
    reference = bench.registry.active_bundle()['registry_ref']
    _, base = bench._base(reference)
    original = next(iter(base['properties'].values()))
    base['properties'] = {f'synthetic-{i:05d}': {**deepcopy(original), 'id': f'synthetic-{i:05d}', 'label': f'性质{i:05d}'} for i in range(5000)}
    ids = [p['id'] for offset in range(0, 5000, 100) for p in bench.list_items('properties', offset=offset, limit=100)['items']]
    assert len(set(ids)) == 5000
    assert bench.list_items('properties', keyword='04999')['total'] == 1
    for budget in (80, 120, 200):
        graph = bench.graph(limit=budget)
        assert graph['meta']['truncated'] and graph['meta']['node_count'] <= budget
    assert bench.summary()['counts']['properties'] == 5000

def test_custom_parent_conditions_cannot_be_bypassed(bench):
    from astroquery_ai.registry.workspace_release import user_type_choices
    ws = bench.create_workspace()['workspace']
    parent = bench.write(ws['id'], 'types', {'label': '限双标签星', 'parent_id': '*', 'conditions': [{'otype': 'pA*'}]}, expected_revision=1)['item']
    child = bench.write(ws['id'], 'types', {'label': '子星', 'parent_id': parent['id']}, expected_revision=2)['item']
    v = bench.validate(ws['id'], expected_revision=3)['validation']
    bench.publish(ws['id'], expected_revision=3, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='conditional-child')
    release = bench.registry.load()
    choice = next(c for c in user_type_choices(release, ['*']) if c['id'] == child['id'])
    reference = {'id': choice['id'], 'version': choice['revision'], 'content_sha256': choice['content_sha256']}
    with pytest.raises(DomainError) as exc:
        bench.registry.support(release, ['*'], 'synthetic-subject', user_type_ref=reference)
    assert exc.value.code == 'USER_TYPE_CONDITIONS'


def test_exact_definition_variants_are_not_collapsed(bench):
    from astroquery_ai.registry.workbench_projection import source_projection, ref
    from astroquery_ai.registry.amendments import reference_key
    from astroquery_ai.registry.models import PropertyDefinition
    from astroquery_ai.runtime.codec import content_hash
    release = bench.registry.load()
    original = next(iter(release['definitions'].values()))
    different = original.model_dump(mode='json')
    different['definition_version'] = 2; different['description'] = 'SYNTHETIC exact alternate source definition'
    different['content_sha256'] = content_hash(different)
    release['definition_views'] = {reference_key(ref(original.model_dump(mode='json'))): original,
        reference_key(ref(different)): PropertyDefinition.model_validate(different)}
    projected = source_projection(release)
    assert len(projected['properties']) == 2
    assert len({p['property_id'] for p in projected['properties'].values()}) == 1
    assert len({p['id'] for p in projected['properties'].values()}) == 2


def test_http_routes_use_same_counts_and_acknowledged_mutations(bench, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from astroquery_ai.api.routes.registry_workbench import register
    app = FastAPI(); register(app, SimpleNamespace(registry_workbench=bench))
    client = TestClient(app)
    assert client.get('/api/registry-workbench/summary').json()['counts']['properties'] == client.get('/api/registry-workbench/properties').json()['total']
    created = client.post('/api/registry-workbench/workspaces', json={})
    assert created.status_code == 200 and created.json()['success']
    ws = created.json()['workspace']
    updated = client.post('/api/registry-workbench/workspaces/' + ws['id'] + '/types', json={'label': 'API星', 'parent_id': '*', 'expected_revision': 1})
    assert updated.status_code == 200 and updated.json()['workspace']['revision'] == 2

def test_user_cannot_inject_review_receipt_into_new_definition(bench):
    ws = bench.create_workspace()['workspace']; original = bench.list_items('properties')['items'][0]
    definition = deepcopy(original['definition']); definition['quantity_key'] = 'synthetic:new-identity'
    created = bench.write(ws['id'], 'properties', {'label': '新定义', 'definition': definition, 'output_profiles': original['output_profiles']}, expected_revision=1)['item']
    assert not created['definition'].get('review_ref')
    assert created['property_id'] == created['definition']['property_id']


def test_binding_profile_edit_is_scoped_and_suspends_knowledge(bench):
    from astroquery_ai.registry.workspace_release import knowledge_compatibility
    ws = bench.create_workspace()['workspace']
    original = bench.list_items('properties')['items'][0]
    binding = bench.list_items('bindings', type_id='*')['items'][0]
    other = bench.list_items('bindings', type_id='pA*')['items'][0]
    profile = deepcopy(original['output_profiles'][0]); profile['unit']['canonical_symbol'] = 'km'
    edited = bench.write(ws['id'], 'bindings', {'output_profile': profile}, item_id=binding['id'], expected_revision=1)['item']
    assert edited['profile_ref'] != binding['profile_ref']
    assert bench.detail('bindings', other['id'], workspace_id=ws['id'])['profile_ref'] == other['profile_ref']
    v = bench.validate(ws['id'], expected_revision=2)['validation']
    assert v['state'] == 'passed'


def test_workspace_wrapper_keeps_original_knowledge_content(bench, tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.science.knowledge import KnowledgeService
    from tests.rebuild.test_knowledge_consumer import package
    knowledge = KnowledgeService(tmp_path/'knowledge', bench.repository, bench.registry)
    bench.knowledge = knowledge
    package(SimpleNamespace(registry=bench.registry), tmp_path/'kb-source')
    knowledge.import_release(tmp_path/'kb-source')
    before = knowledge.load()
    ws = bench.create_workspace()['workspace']
    v = bench.validate(ws['id'], expected_revision=1)['validation']
    assert v['state'] == 'passed'
    result = bench.publish(ws['id'], expected_revision=1, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='kb-wrapper')
    after = knowledge.load(result['bundle']['knowledge_ref'])
    assert after['manifest']['schema_version'] == 'insight-knowledge-workspace/1'
    assert after['entries'] == before['entries']
    assert after['sources'] == before['sources']
    assert knowledge.load()['manifest'] == after['manifest']

def test_verified_source_unit_literals_are_not_reinterpreted_by_draft_validation(bench):
    from astroquery_ai.registry.workbench_validation import validate_projection
    _, base = bench._base(bench.registry.active_bundle()['registry_ref'])
    projection = deepcopy(base)
    profile = next(iter(projection['properties'].values()))['output_profiles'][0]
    profile['unit']['canonical_symbol'] = 'source-native-coordinate'
    # Structural fixture for a profile already verified by its source importer.
    errors, _ = validate_projection(projection, bench._capabilities(bench.registry.load()))
    assert not any(error['code'] == 'INVALID_UNIT' for error in errors)


def test_qualification_reuse_requires_full_exact_dependency_closure(bench):
    from astroquery_ai.registry.workspace_release import qualification_base_ref
    ws = bench.create_workspace()['workspace']; v = bench.validate(ws['id'], expected_revision=1)['validation']
    bench.publish(ws['id'], expected_revision=1, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='deps')
    release = bench.registry.load(); support = bench.registry.support(release, ['*'], 'synthetic-subject')
    assert qualification_base_ref(release, support['bindings'])
    modified = deepcopy(support['bindings']); modified[0]['dependency_refs'][0]['content_sha256'] = '0' * 64
    assert qualification_base_ref(release, modified) is None

def test_graph_overview_budget_keeps_property_nodes_and_edges(bench):
    _, base = bench._base(bench.registry.active_bundle()['registry_ref'])
    original_type = base['types']['*']; original_binding = next(iter(base['bindings'].values()))
    for number in range(100):
        identifier = f'SYNTHETIC-{number}'
        base['types'][identifier] = {**deepcopy(original_type), 'id': identifier, 'code': identifier, 'standard_otype': identifier}
        base['bindings'][identifier] = {**deepcopy(original_binding), 'id': identifier, 'type_id': identifier}
    graph = bench.graph(limit=80)
    assert any(node['kind'] == 'property' for node in graph['nodes'])
    assert graph['edges']


def test_concurrent_writes_have_one_winner_and_one_conflict(bench):
    from concurrent.futures import ThreadPoolExecutor
    ws = bench.create_workspace()['workspace']
    def edit(label):
        try:
            return bench.write(ws['id'], 'types', {'label': label, 'parent_id': '*'}, expected_revision=1)['success']
        except DomainError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(edit, ['A', 'B']))
    assert result.count(True) == 1 and result.count('WORKSPACE_CONFLICT') == 1


def test_persistence_failure_is_explicit_503_not_false_ack(bench, monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    @contextmanager
    def failed_transaction():
        raise sqlite3.OperationalError('injected disk error')
        yield
    monkeypatch.setattr(bench.repository, 'transaction', failed_transaction)
    with pytest.raises(DomainError) as exc:
        bench.create_workspace()
    assert exc.value.status == 503

@pytest.mark.parametrize('mutation,expected_code', [
    ('category', 'VALUE_REPRESENTATION_CONFLICT'),
    ('policy', 'INVALID_POLICY'),
])
def test_profile_semantics_and_exact_policy_refs_fail_validation(bench, mutation, expected_code):
    ws = bench.create_workspace()['workspace']; prop = bench.list_items('properties')['items'][0]
    profiles = deepcopy(prop['output_profiles'])
    if mutation == 'category':
        profiles[0]['representation'] = {'kind': 'category'}
    else:
        profiles[0]['conversion_policy_ref'] = {'id': profiles[0]['conversion_policy_ref']['id']}
    bench.write(ws['id'], 'properties', {'output_profiles': profiles}, item_id=prop['id'], expected_revision=1)
    result = bench.validate(ws['id'], expected_revision=2)['validation']
    assert result['state'] == 'failed'
    assert any(e['code'] == expected_code for e in result['errors'])


def test_scientific_hashes_and_versions_are_server_derived(bench):
    ws = bench.create_workspace()['workspace']; prop = bench.list_items('properties')['items'][0]
    definition = deepcopy(prop['definition']); definition.update(content_sha256='0'*64, definition_version=999)
    profiles = deepcopy(prop['output_profiles']); profiles[0].update(content_sha256='0'*64, version=999)
    edited = bench.write(ws['id'], 'properties', {'definition': definition, 'output_profiles': profiles}, item_id=prop['id'], expected_revision=1)['item']
    assert edited['definition_ref'] == prop['definition_ref']
    assert edited['output_profiles'] == prop['output_profiles']

def test_published_read_does_not_invalidate_validated_draft(bench):
    ws = bench.create_workspace()['workspace']; v = bench.validate(ws['id'], expected_revision=1)['validation']
    bench.summary()
    result = bench.publish(ws['id'], expected_revision=1, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='read-stability')
    assert result['success']


def test_disabled_ancestor_cannot_accept_new_child(bench):
    ws = bench.create_workspace()['workspace']
    parent = bench.write(ws['id'], 'types', {'label': '父类型', 'parent_id': '*'}, expected_revision=1)['item']
    bench.write(ws['id'], 'types', {'status': 'disabled'}, item_id=parent['id'], expected_revision=2)
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'types', {'label': '子类型', 'parent_id': parent['id']}, expected_revision=3)
    assert exc.value.code == 'TYPE_PARENT_REQUIRED'

def test_parent_with_descendant_cannot_reparent_silently(bench):
    ws = bench.create_workspace()['workspace']
    parent = bench.write(ws['id'], 'types', {'label': '父', 'parent_id': '*'}, expected_revision=1)['item']
    bench.write(ws['id'], 'types', {'label': '子', 'parent_id': parent['id']}, expected_revision=2)
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'types', {'parent_id': 'pA*'}, item_id=parent['id'], expected_revision=3)
    assert exc.value.code == 'REGISTRY_DEPENDENTS'


def test_exact_missing_knowledge_mapping_does_not_count_as_available(bench):
    from astroquery_ai.registry.workspace_release import knowledge_compatibility
    _, projection = bench._base(bench.registry.active_bundle()['registry_ref'])
    binding = next(iter(projection['bindings'].values()))
    knowledge = {'entries': {}, 'data': {'bindings': [{'item_id': 'missing-item', 'otype': binding['type_id'],
        'definition_ref': binding['definition_ref'], 'output_profile_ref': binding['profile_ref'], 'entry_ids': [],
        'status': 'missing', 'reason': 'No author coverage'}]}}
    result = knowledge_compatibility(knowledge, projection)
    assert result['available'] == 0 and result['missing'] == 1
    assert any(g['reason'] == 'No author coverage' for g in result['gaps'])


def test_graph_aggregates_represent_every_omitted_record_truthfully(bench):
    _, base = bench._base(bench.registry.active_bundle()['registry_ref'])
    prop = next(iter(base['properties'].values()))
    for number in range(200):
        base['properties'][str(number)] = {**deepcopy(prop), 'id': str(number)}
    graph = bench.graph(limit=80)
    aggregates = [n for n in graph['nodes'] if n['kind'] == 'aggregate']
    assert aggregates and graph['meta']['node_count'] <= 80
    assert graph['meta']['represented_entries'] == graph['meta']['matched_entries']
    assert sum(n['count'] for n in aggregates) + graph['meta']['shown_entries'] == graph['meta']['represented_entries']

def test_shared_definition_edit_preserves_binding_owned_profile(bench):
    ws = bench.create_workspace()['workspace']; prop = bench.list_items('properties')['items'][0]
    binding = bench.list_items('bindings', type_id='*')['items'][0]
    profile = deepcopy(prop['output_profiles'][0]); profile['unit']['canonical_symbol'] = 'km'
    bench.write(ws['id'], 'bindings', {'output_profile': profile}, item_id=binding['id'], expected_revision=1)
    definition = deepcopy(prop['definition']); definition['description'] = '用户补充的科学解释'
    bench.write(ws['id'], 'properties', {'definition': definition}, item_id=prop['id'], expected_revision=2)
    updated = bench.detail('bindings', binding['id'], workspace_id=ws['id'])
    assert updated['output_profile']['unit']['canonical_symbol'] == 'km'
    assert updated['output_profile']['definition_version'] == updated['definition_ref']['version']
    assert bench.validate(ws['id'], expected_revision=3)['validation']['state'] == 'passed'

def test_custom_code_is_saved_and_duplicate_codes_are_rejected(bench):
    ws = bench.create_workspace()['workspace']
    item = bench.write(ws['id'], 'types', {'label': '编码星', 'code': 'MY_STAR', 'parent_id': '*'}, expected_revision=1)['item']
    assert item['code'] == 'MY_STAR'
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'types', {'label': '重复编码星', 'code': 'MY_STAR', 'parent_id': '*'}, expected_revision=2)
    assert exc.value.code == 'DUPLICATE_TYPE_CODE'


def test_corrupt_knowledge_stage_does_not_activate(bench, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pathlib import Path
    from astroquery_ai.science.knowledge import KnowledgeService
    from tests.rebuild.test_knowledge_consumer import package
    bench.knowledge = KnowledgeService(tmp_path/'knowledge', bench.repository, bench.registry)
    package(SimpleNamespace(registry=bench.registry), tmp_path/'kb-source')
    bench.knowledge.import_release(tmp_path/'kb-source')
    active = bench.registry.active_bundle()
    ws = bench.create_workspace()['workspace']; v = bench.validate(ws['id'], expected_revision=1)['validation']
    original = Path.write_bytes
    def corrupt(path, value):
        return original(path, b'{}' if path.name == 'compatibility.json' else value)
    monkeypatch.setattr(Path, 'write_bytes', corrupt)
    with pytest.raises(DomainError):
        bench.publish(ws['id'], expected_revision=1, validation_id=v['id'], expected_active_bundle_id=active['id'], idempotency_key='corrupt-stage')
    assert bench.registry.active_bundle() == active
    assert bench.get_workspace(ws['id'])['status'] == 'draft'

def test_reference_metadata_does_not_break_exact_author_mapping(bench):
    from astroquery_ai.registry.workspace_release import knowledge_compatibility
    _, projection = bench._base(bench.registry.active_bundle()['registry_ref'])
    binding = next(iter(projection['bindings'].values()))
    knowledge = {'entries': {'author.one': {'entry_id': 'author.one', 'title': '原文'}}, 'data': {'bindings': [
        {'item_id': 'mapping.one', 'otype': binding['type_id'], 'definition_ref': {**binding['definition_ref'], 'version': str(binding['definition_ref']['version']), 'kind': 'definition'},
         'output_profile_ref': {**binding['profile_ref'], 'kind': 'output_profile'}, 'entry_ids': ['author.one'], 'status': 'covered'}]}}
    result = knowledge_compatibility(knowledge, projection)
    assert result['available'] == 1
    assert result['links'][binding['property_key']][0]['entry_id'] == 'author.one'

def test_duplicate_profile_ids_are_edited_by_full_exact_reference(bench):
    from astroquery_ai.registry.workbench_projection import ref
    from astroquery_ai.runtime.codec import content_hash
    _, base = bench._base(bench.registry.active_bundle()['registry_ref'])
    prop = next(iter(base['properties'].values())); first = deepcopy(prop['output_profiles'][0])
    second = deepcopy(first); second['version'] = 2; second['unit']['canonical_symbol'] = 'km'; second['content_sha256'] = content_hash(second)
    prop['output_profiles'].append(second)
    bindings = list(base['bindings'].values()); bindings[1]['profile_ref'] = ref(second, 'profile')
    ws = bench.create_workspace()['workspace']
    profiles = deepcopy(prop['output_profiles']); profiles[1]['unit']['canonical_symbol'] = 'cm'
    edited = bench.write(ws['id'], 'properties', {'output_profiles': profiles}, item_id=prop['id'], expected_revision=1)['item']
    assert edited['output_profiles'][0] == first
    assert edited['output_profiles'][1]['version'] == 3
    first_binding = bench.detail('bindings', bindings[0]['id'], workspace_id=ws['id'])
    second_binding = bench.detail('bindings', bindings[1]['id'], workspace_id=ws['id'])
    assert first_binding['profile_ref'] == ref(first, 'profile')
    assert first_binding.get('automatic_execution_ready', True)
    assert second_binding['profile_ref'] == ref(edited['output_profiles'][1], 'profile')

def test_type_color_is_safe_configuration_data_and_graph_has_real_counts(bench):
    ws = bench.create_workspace()['workspace']
    with pytest.raises(DomainError) as exc:
        bench.write(ws['id'], 'types', {'label': '颜色星', 'parent_id': '*', 'color': 'invalid css'}, expected_revision=1)
    assert exc.value.code == 'INVALID_TYPE_COLOR'
    bench.write(ws['id'], 'types', {'color': '#123abc'}, item_id='*', expected_revision=1)
    node = next(n for n in bench.graph(workspace_id=ws['id'])['nodes'] if n.get('record_id') == '*')
    assert node['color'] == '#123abc' and node['property_count'] == 1 and node['code'] == '*'

def test_audited_duplicate_quantity_identity_survives_explanatory_edit(bench):
    _, base = bench._base(bench.registry.active_bundle()['registry_ref'])
    original = next(iter(base['properties'].values()))
    duplicate = deepcopy(original); duplicate['id'] = 'source-alternate-record'; duplicate['property_id'] = 'source-alternate-property'
    duplicate['definition']['property_id'] = duplicate['property_id']
    duplicate['source_quantity_identity'] = {'property_id': duplicate['property_id'], 'quantity_key': duplicate['definition']['quantity_key']}
    base['properties'][duplicate['id']] = duplicate
    ws = bench.create_workspace()['workspace']
    definition = deepcopy(original['definition']); definition['description'] = '更完整的用户说明'
    bench.write(ws['id'], 'properties', {'definition': definition}, item_id=original['id'], expected_revision=1)
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert not any(e['code'] == 'DUPLICATE_QUANTITY_IDENTITY' for e in validation['errors'])

def test_standard_type_conditions_restrict_runtime_support(bench):
    ws = bench.create_workspace()['workspace']
    bench.write(ws['id'], 'types', {'conditions': [{'otype': 'pA*'}]}, item_id='*', expected_revision=1)
    v = bench.validate(ws['id'], expected_revision=2)['validation']
    bench.publish(ws['id'], expected_revision=2, validation_id=v['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='standard-conditions')
    assert bench.registry.support(bench.registry.load(), ['*'], 'synthetic-subject')['bindings'] == []

def test_binding_owned_profile_can_be_removed_without_global_edit(bench):
    ws = bench.create_workspace()['workspace']; prop = bench.list_items('properties')['items'][0]
    binding = bench.list_items('bindings', type_id='*')['items'][0]
    profile = deepcopy(prop['output_profiles'][0]); profile['unit']['canonical_symbol'] = 'km'
    bench.write(ws['id'], 'bindings', {'output_profile': profile}, item_id=binding['id'], expected_revision=1)
    restored = bench.write(ws['id'], 'bindings', {'output_profile': None, 'profile_ref': binding['profile_ref']}, item_id=binding['id'], expected_revision=2)['item']
    assert 'output_profile' not in restored
    assert restored['profile_ref'] == binding['profile_ref']
    assert restored['automatic_execution_ready'] is True
    assert bench.detail('properties', prop['id'], workspace_id=ws['id'])['output_profiles'] == prop['output_profiles']


def test_binding_owned_profile_must_match_its_exact_reference(bench):
    ws = bench.create_workspace()['workspace']; prop = bench.list_items('properties')['items'][0]
    binding = bench.list_items('bindings', type_id='*')['items'][0]
    profile = deepcopy(prop['output_profiles'][0]); profile['unit']['canonical_symbol'] = 'km'
    bench.write(ws['id'], 'bindings', {'output_profile': profile}, item_id=binding['id'], expected_revision=1)
    edited = bench.write(ws['id'], 'bindings', {'profile_ref': binding['profile_ref']},
        item_id=binding['id'], expected_revision=2)['item']
    assert edited['automatic_execution_ready'] is False
    validation = bench.validate(ws['id'], expected_revision=3)['validation']
    assert validation['state'] == 'failed'
    assert any(error['code'] == 'INVALID_EXACT_REFERENCE' for error in validation['errors'])

def test_unbound_custom_type_is_searchable_and_focusable_in_graph(bench):
    ws = bench.create_workspace()['workspace']
    created = bench.write(ws['id'], 'types', {'label': '隔离验证星系', 'code': 'QA_GALAXY', 'parent_id': '*'}, expected_revision=1)['item']
    matching = bench.list_items('types', workspace_id=ws['id'], keyword='隔离')['items']
    assert [item['id'] for item in matching] == [created['id']]
    overview = bench.graph(workspace_id=ws['id'], keyword='隔离')
    assert [node['record_id'] for node in overview['nodes']] == [created['id']]
    assert overview['edges'] == []
    assert overview['meta']['total_types'] == 1 and overview['meta']['total_properties'] == 0
    focused = bench.graph(workspace_id=ws['id'], view='type', focus_id=created['id'])
    assert [node['record_id'] for node in focused['nodes']] == [created['id']]
    assert focused['edges'] == []
    prop = bench.list_items('properties')['items'][0]
    property_focus = bench.graph(workspace_id=ws['id'], view='property', focus_id=prop['id'])
    assert created['id'] not in {node.get('record_id') for node in property_focus['nodes']}
