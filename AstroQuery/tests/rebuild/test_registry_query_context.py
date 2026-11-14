"""Synthetic version/subtype protocol tests, not scientific qualification."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from astroquery_ai.query import registry_context
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError


def bundle(identifier):
    return {'id': identifier, 'revision': 1,
            'registry_ref': {'id': identifier + '-registry', 'version': 1, 'content_sha256': 'a' * 64},
            'knowledge_ref': {'id': identifier + '-knowledge', 'version': 1, 'content_sha256': 'b' * 64}}


def test_new_query_pins_one_bundle_and_restart_keeps_it(tmp_path, monkeypatch):
    app = Application(tmp_path, allow_synthetic=True)
    current = bundle('first')
    monkeypatch.setattr(app.registry, 'active_bundle', lambda conn=None: deepcopy(current))
    tid = str(uuid4())
    app.create('SYNTHETIC target', tid)
    current.update(bundle('second'))
    view = app.view(tid)
    assert view['draft']['registry_bundle'] == bundle('first')
    assert view['draft']['registry_release'] == bundle('first')['registry_ref']
    with app.repository.transaction() as conn:
        draft = app._draft(conn, tid)
        app._save_draft(conn, draft)
    view = app.view(tid)
    app.draft_action(tid, {'protocol_version': 2, 'operation_id': str(uuid4()),
        'expected_revision': view['revision'], 'question_id': view['draft']['pending_question']['question_id'],
        'action': {'type': 'restart_draft'}})
    assert app.view(tid)['draft']['registry_bundle'] == bundle('first')
    assert app.view(tid)['draft']['registry_release'] == bundle('first')['registry_ref']


def test_reload_rejects_outstanding_preparation_without_stranding_job(tmp_path, monkeypatch):
    app = Application(tmp_path, allow_synthetic=True)
    monkeypatch.setattr(app.registry, 'active_bundle', lambda conn=None: bundle('first'))
    tid = str(uuid4())
    app.create('SYNTHETIC target', tid)
    view = app.view(tid)
    with pytest.raises(DomainError) as error:
        app.draft_action(tid, {'protocol_version': 2, 'operation_id': str(uuid4()),
            'expected_revision': view['revision'], 'question_id': None, 'action': {'type': 'reload_registry'}})
    assert error.value.code == 'REGISTRY_UPGRADE_BUSY'
    assert app.view(tid)['draft']['revision'] == 1
    job = app.repository.claim_job('synthetic-worker', task_id=tid)
    assert job['payload']['draft_revision'] == 1


def test_only_explicit_upgrade_replaces_bundle_and_clears_scope():
    app = SimpleNamespace(registry=SimpleNamespace(active_bundle=lambda conn=None: bundle('second')))
    draft = {'registry_bundle': bundle('first'), 'registry_release': bundle('first')['registry_ref'],
             'user_type_ref': {'id': 'subtype'}, 'property_support': {'bindings': []}}
    registry_context.pin_bundle(app, draft)
    assert draft['registry_bundle']['id'] == 'first'
    registry_context.pin_bundle(app, draft, refresh=True)
    assert draft['registry_bundle'] == bundle('second')
    assert draft['user_type_ref'] is None
    assert draft['property_support'] is None


def test_verified_types_never_include_unverified_or_another_object_assertions():
    target = {'target_id': 'target', 'primary_otype': 'G', 'classification_assertions': [
        {'canonical_otype': 'AGN', 'state': 'current_verified', 'subject_identity_ref': 'target', 'evidence_refs': ['proof']},
        {'canonical_otype': '*', 'state': 'candidate', 'subject_identity_ref': 'target', 'evidence_refs': ['proof']},
        {'canonical_otype': 'QSO', 'state': 'current_verified', 'subject_identity_ref': 'other', 'evidence_refs': ['proof']}]}
    before = deepcopy(target)
    assert registry_context.verified_types(target) == ['AGN', 'G']
    assert target == before


def test_pinned_knowledge_requires_exact_hash_and_pair():
    expected = bundle('first')
    package = {'manifest': {'schema_version': 'insight-knowledge-workspace/1',
        'release_id': expected['knowledge_ref']['id'], 'content_sha256': 'b' * 64,
        'registry_release_ref': expected['registry_ref']}}
    app = SimpleNamespace(knowledge=SimpleNamespace(load=lambda ref=None: deepcopy(package)))
    assert registry_context.pinned_knowledge(app, {'registry_bundle': expected}) == package
    package['manifest']['registry_release_ref'] = bundle('other')['registry_ref']
    with pytest.raises(DomainError, match='版本组合'):
        registry_context.pinned_knowledge(app, {'registry_bundle': expected})
    with pytest.raises(DomainError, match='版本组合'):
        registry_context.pinned_knowledge(app, {'registry_release': expected['registry_ref']})


def test_changing_verified_target_drops_previous_user_subtype_without_mutating_external_type(monkeypatch):
    from astroquery_ai.query import drafts
    binding = {'property_id': 'p'}
    seen = []
    app = SimpleNamespace(registry=SimpleNamespace(support=lambda *args, **kwargs:
        seen.append(kwargs) or {'bindings': [binding], 'support_hash': 'hash'}))
    target = {'target_id': 'new-target', 'primary_otype': '*', 'classification_assertions': []}
    draft = {'task_id': 'task', 'target': {'target_id': 'old-target'},
        'user_type_ref': {'id': 'old-galaxy-subtype'}, 'selected_property_ids': []}
    release = {'manifest': {}, 'data': {'type-profiles': [{'otype': '*', 'subject_class_id': 'subject'}]}}
    monkeypatch.setattr(drafts, 'subtype_choices', lambda release, target: [])
    drafts._bind_target(app, draft, target, release)
    assert draft['target'] == target and target['primary_otype'] == '*'
    assert draft['user_type_ref'] is None
    assert seen == [{}]


def test_base_qualification_only_reused_for_unchanged_exact_dependencies():
    definition = {'property_id': 'SYNTHETIC p', 'definition_version': 1, 'content_sha256': 'c' * 64}
    profile = {'profile_id': 'SYNTHETIC output', 'version': 1, 'content_sha256': 'd' * 64}
    frozen = {'definition': definition, 'output_profile': profile, 'rule_refs': []}
    from astroquery_ai.registry.workspace_release import release_ref
    from astroquery_ai.registry.workbench_projection import ref
    base = {'manifest': {'release_id': 'SYNTHETIC base', 'content_sha256': 'e' * 64}}
    release = {'manifest': {'release_id': 'SYNTHETIC local', 'content_sha256': 'f' * 64},
        'base_release': base, 'workspace': {'projection': {
            'properties': {'p': {'status': 'active', 'automatic_conversion_ready': True,
                'definition_ref': ref(definition), 'output_profiles': [profile]}},
            'bindings': {'b': {'status': 'active', 'source_binding': frozen}}}}}
    app = SimpleNamespace(registry=SimpleNamespace(load=lambda identifier: release))
    spec = {'registry_release': release_ref(release), 'properties': [frozen]}
    assert registry_context.qualification_reference(app, spec) == release_ref(base)
    changed = deepcopy(frozen)
    changed['output_profile']['content_sha256'] = '0' * 64
    assert registry_context.qualification_reference(app, {**spec, 'properties': [changed]}) is None
    spec['registry_release']['content_sha256'] = '1' * 64
    assert registry_context.qualification_reference(app, spec) is None


def test_publication_and_rollback_only_change_subsequent_query_pins(tmp_path):
    from tests.rebuild.registry_fixture import make_release
    app = Application(tmp_path / 'runtime', allow_synthetic=True)
    make_release(tmp_path / 'source')
    app.registry.import_release(tmp_path / 'source')
    original = app.registry.active_bundle()
    old_task, new_task, rolled_task = [str(uuid4()) for _ in range(3)]
    app.create('SYNTHETIC before publish', old_task)
    bench = app.registry_workbench
    workspace = bench.create_workspace()['workspace']
    validation = bench.validate(workspace['id'], expected_revision=1)['validation']
    published = bench.publish(workspace['id'], expected_revision=1, validation_id=validation['id'],
        expected_active_bundle_id=original['id'], idempotency_key='SYNTHETIC publish')
    app.create('SYNTHETIC after publish', new_task)
    assert app.view(old_task)['draft']['registry_bundle'] == original
    assert app.view(new_task)['draft']['registry_bundle'] == published['bundle']
    bench.activate(original['id'], expected_active_bundle_id=published['bundle']['id'],
        idempotency_key='SYNTHETIC rollback')
    app.create('SYNTHETIC after rollback', rolled_task)
    assert app.view(rolled_task)['draft']['registry_bundle']['registry_ref'] == original['registry_ref']
    assert app.view(new_task)['draft']['registry_bundle'] == published['bundle']


def test_local_names_reach_intent_matching_without_rewriting_scientific_definition():
    from astroquery_ai.query.semantic_selection import binding_view
    definition = {'property_id': 'p', 'definition_version': 1, 'content_sha256': 'd',
                  'name_cn': '原规范名称', 'description': '原科学定义'}
    output = {'profile_id': 'o', 'version': 1, 'content_sha256': 'h'}
    support = {'bindings': [{'property_id': 'p', 'definition': deepcopy(definition), 'output_profile': output}]}
    release = {'workspace': {'projection': {'properties': {'p': {
        'definition_ref': {'id': 'p', 'version': 1, 'content_sha256': 'd'},
        'label': '我的显示名', 'aliases': ['我的检索别名']}}}}}
    registry_context.apply_local_labels(release, support)
    binding = support['bindings'][0]
    assert binding['definition'] == definition
    prompt = binding_view(binding)
    assert prompt['local_labels']['aliases'] == ['我的检索别名']
    assert prompt['local_labels']['display_name'] == '我的显示名'
