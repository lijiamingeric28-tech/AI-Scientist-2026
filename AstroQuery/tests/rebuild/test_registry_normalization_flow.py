"""Offline workbench-to-normalization protocol coverage; no scientific approval."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from astroquery_ai.query import drafts
from astroquery_ai.runtime import run_policy
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.scenario import application, confirmed_case, run_until_wait
from tests.rebuild.test_new_end_to_end import SyntheticIdentity


def publish(bench, workspace):
    validation = bench.validate(workspace['id'], expected_revision=workspace['revision'])['validation']
    assert validation['state'] == 'passed'
    return bench.publish(workspace['id'], expected_revision=workspace['revision'],
        validation_id=validation['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'],
        idempotency_key=str(uuid4()))


def confirm(app, task_id):
    state = app.view(task_id)
    assert state['pending'] and state['pending']['preview'], state.get('draft')
    return app.draft_action(task_id, {'protocol_version': 2, 'operation_id': str(uuid4()),
        'expected_revision': state['revision'], 'question_id': state['pending']['question_id'],
        'action': {'type': 'confirm', 'preview_hash': state['pending']['preview']['preview_hash']}})


def test_published_metadata_and_subtype_reach_normalization_without_changing_old_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(run_policy, 'request_policy', lambda _, preferences=None: deepcopy(run_policy.LEGACY_RUN_POLICY))

    async def run():
        app = application(tmp_path / 'runtime')
        completed, scheduler = await confirmed_case(app)
        with app.repository.read() as conn:
            historical = deepcopy(app.delivery.get(conn, completed['task_id']))
        original = app.registry.active_bundle()
        old_id = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
        await run_until_wait(app, scheduler)
        assert app.view(old_id)['pending']['preview']

        bench = app.registry_workbench
        workspace = bench.create_workspace()['workspace']
        prop = bench.list_items('properties')['items'][0]
        workspace = bench.write(workspace['id'], 'properties',
            {'label': '我的规范长度', 'aliases': ['本地长度别名']}, item_id=prop['id'],
            expected_revision=workspace['revision'])['workspace']
        created = bench.write(workspace['id'], 'types', {'label': '用户指定测试子类', 'parent_id': 'pA*'},
            expected_revision=workspace['revision'])
        extra = bench.write(workspace['id'], 'properties', {'label': '用户附加长度',
            'family_id': prop['family_id'], 'definition': {'quantity_key': 'user:extra_length',
                'quantity_kind': 'length', 'subject_class_id': 'synthetic-subject'},
            'output_profiles': deepcopy(prop['output_profiles']), 'type_ids': ['pA*']},
            expected_revision=created['workspace']['revision'])
        published = publish(bench, extra['workspace'])
        new_id = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
        await run_until_wait(app, scheduler)
        state = app.view(new_id)
        assert state['pending'] and state['pending']['preview'], state['draft']
        assert state['draft']['registry_bundle'] == published['bundle']
        assert state['draft']['property_support']['bindings'][0]['display_name'] == '我的规范长度'
        additional = next(b for b in state['draft']['property_support']['bindings'] if b.get('display_name') == '用户附加长度')
        assert additional['execution_capabilities']['native']['ready']
        assert not additional['execution_capabilities']['normalization']['ready']
        app.draft_action(new_id, {'protocol_version': 2, 'operation_id': str(uuid4()),
            'expected_revision': state['revision'], 'question_id': state['pending']['question_id'],
            'action': {'type': 'select_user_type', 'type_id': created['item']['id']}})
        await run_until_wait(app, scheduler)
        confirm(app, old_id)
        confirm(app, new_id)
        bench.activate(original['id'], expected_active_bundle_id=published['bundle']['id'], idempotency_key=str(uuid4()))
        # Reopen the persisted application after rollback, then execute both
        # frozen requests with isolated synthetic providers.
        restored = Application(tmp_path / 'runtime', allow_synthetic=True)
        restored.models, restored.identity = app.models, SyntheticIdentity(restored)
        restored.http.transport = app.http.transport
        restored.configuration.runtime['ads_api_token'] = 'SYNTHETIC-NOT-A-REAL-TOKEN'
        app, scheduler = restored, Scheduler(restored)
        await run_until_wait(app, scheduler)
        for task_id, bundle in ((old_id, original), (new_id, published['bundle'])):
            state = app.view(task_id)
            assert state['lifecycle'] == 'completed', state
            with app.repository.read() as conn:
                reference = loads(app.repository.task(conn, task_id)['query_ref'])
                spec = app.repository.object(conn, task_id, 'confirmed_query', reference['id'], reference['version'])
                assert spec['registry_bundle'] == bundle
                assert spec['target']['primary_otype'] == 'pA*'
                if task_id == new_id:
                    assert spec['user_type_ref']['id'] == created['item']['id']
                    assert spec['properties'][0]['display_aliases'] == ['本地长度别名']
                delivery = app.delivery.get(conn, task_id)
                assert len(delivery['measurements']) == len(delivery['derived']) == 1
                output = spec['properties'][0]['output_profile']
                assert delivery['derived'][0]['output_profile_ref'] == {
                    'id': output['profile_id'], 'version': output['version'], 'content_sha256': output['content_sha256']}
                assert delivery['provenance_bundle']['processing_receipts'][0]['postcheck'] == 'passed'
        with app.repository.read() as conn:
            assert app.delivery.get(conn, completed['task_id']) == historical

    asyncio.run(run())


def test_new_applicability_subject_is_reported_in_query_capability_gaps():
    seen = []
    binding = {'property_id': 'base', 'definition': {
        'property_id': 'base', 'definition_version': 1, 'content_sha256': 'a' * 64}}
    def support(release, types, subject, **kwargs):
        seen.append(subject)
        return {'bindings': [binding] if subject == 'base-subject' else [],
            'gaps': [{'property_id': 'user-property', 'property_key': 'new', 'automatic_execution_ready': False}] if subject == 'new-subject' else []}
    app = SimpleNamespace(registry=SimpleNamespace(support=support))
    release = {'manifest': {'schema_version': 'registry-workspace/1'},
        'data': {'type-profiles': [{'otype': '*', 'subject_class_id': 'base-subject'}]},
        'context_bindings': {}, 'workspace': {'projection': {
            'types': {'*': {'id': '*', 'standard_otype': '*', 'status': 'active'}},
            'properties': {'new': {'id': 'new', 'label': '用户新增性质', 'status': 'active',
                'definition_ref': {'id': 'user-property', 'version': 1, 'content_sha256': 'b' * 64},
                'definition': {'subject_class_id': 'new-subject'}}},
            'bindings': {'new': {'type_id': '*', 'property_key': 'new', 'status': 'active'}}}}}
    draft = {'task_id': 'task', 'selected_property_ids': []}
    target = {'target_id': 'target', 'primary_otype': '*', 'classification_assertions': []}
    drafts._bind_target(app, draft, target, release)
    assert set(seen) == {'base-subject', 'new-subject'}
    assert draft['property_support']['gaps'][0]['property_id'] == 'user-property'
    assert draft['property_support']['gaps'][0]['label'] == '用户新增性质'


@pytest.mark.parametrize('changed', [False, True])
def test_published_scope_can_reuse_exact_original_reader_profile(tmp_path, monkeypatch, changed):
    from astroquery_ai.registry.workspace_release import release_ref
    from astroquery_ai.science.reader_profiles import pin_reader_profile
    app = application(tmp_path / 'runtime')
    base_ref = release_ref(app.registry.load())
    for _ in range(2):
        workspace = app.registry_workbench.create_workspace()['workspace']
        publish(app.registry_workbench, workspace)
    release = app.registry.load()
    binding = deepcopy(app.registry.support(release, ['pA*'], 'synthetic-subject')['bindings'][0])
    task_id = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
    qref = {'id': 'SYNTHETIC reader qualification', 'version': 1, 'content_sha256': 'a' * 64}
    profile = {'registry_ref': base_ref, 'definition_refs': [
        {'id': binding['property_id'], 'version': binding['definition']['definition_version'],
         'content_sha256': binding['definition']['content_sha256']}],
        'qualification_ref': qref, 'settings': {'reader_strategy': 'synthetic'}, 'evidence_refs': []}
    monkeypatch.setattr(app.profile_authority, 'load', lambda conn, owner: ({'state': 'qualified'}, qref))
    with app.repository.transaction() as conn:
        reference = {**app.repository.put_object(conn, task_id, 'reader_profile', 'synthetic-profile', 1, profile), 'task_id': task_id}
        conn.execute('INSERT INTO settings VALUES(?,?,1)', ('reader_profile:M06', canonical(reference)))
        if changed:
            binding['dependency_refs'][0]['content_sha256'] = '0' * 64
        spec = {'registry_release': release_ref(release), 'properties': [binding]}
        if changed:
            with pytest.raises(DomainError) as exc:
                pin_reader_profile(app, conn, task_id, spec)
            assert exc.value.code == 'READER_PROFILE_UNVERIFIED'
        else:
            pin = pin_reader_profile(app, conn, task_id, spec)
            assert pin['registry_ref'] == spec['registry_release']
            assert pin['source_registry_ref'] == base_ref
            assert pin['reference'] == reference
            assert pin_reader_profile(app, conn, task_id, spec) == pin


def test_base_revocations_apply_to_descendant_confirmation_and_runtime_guard(tmp_path):
    from astroquery_ai.registry.workspace_release import release_ref
    app = application(tmp_path / 'runtime')
    base_ref = release_ref(app.registry.load())
    for _ in range(2):
        publish(app.registry_workbench, app.registry_workbench.create_workspace()['workspace'])
    release = app.registry.load()
    binding = app.registry.support(release, ['pA*'], 'synthetic-subject')['bindings'][0]
    task_id = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
    spec = {'registry_release': release_ref(release), 'properties': [binding],
        'dependencies': binding['dependency_refs']}
    with app.repository.transaction() as conn:
        ref = app.repository.put_object(conn, task_id, 'confirmed_query', 'synthetic-spec', 1, spec)
        app.repository.mutate_task(conn, task_id, lifecycle='queued', query_ref=canonical(ref).decode())
        conn.execute('INSERT INTO revocations(event_id,release_id,dependency_id,reason,evidence) VALUES(?,?,?,?,?)',
            ('SYNTHETIC revocation', base_ref['id'], binding['dependency_refs'][0]['id'], 'SYNTHETIC invalidation', canonical({})))
        assert app.registry.check_eligibility(conn, release['manifest']['release_id'], spec['dependencies'])['state'] == 'blocked'
        task = app.repository.task(conn, task_id)
        with pytest.raises(DomainError) as exc:
            app.repository.guard_definitions(conn, task)
        assert exc.value.code == 'DEFINITION_INVALIDATED'
