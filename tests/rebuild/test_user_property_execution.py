from copy import deepcopy

import pytest

from tests.rebuild.test_registry_workbench import bench  # noqa: F401


def create_property(bench, examples=None, unit=None, representation=None):
    ws = bench.create_workspace()['workspace']
    source = bench.list_items('properties')['items'][0]
    profile = deepcopy(source['output_profiles'][0])
    if unit:
        profile['unit'].update(unit)
    if representation:
        profile['representation'] = representation
    for key in ('profile_id', 'version', 'content_sha256', 'property_id', 'definition_version', 'review_ref'):
        profile.pop(key, None)
    policy = next(p for p in bench.summary()['capabilities']['conversion_policies'] if p.get('user_declared'))
    profile['conversion_policy_ref'] = {'id': policy['policy_id'], 'version': policy['version'], 'content_sha256': policy['content_sha256']}
    item = bench.write(ws['id'], 'properties', {'label': 'User length', 'description': 'Locally declared length',
        'family_id': source['family_id'], 'definition': {'quantity_key': 'user:length', 'quantity_kind': 'length',
        'subject_class_id': 'synthetic-subject'}, 'output_profiles': [profile], 'type_ids': ['*'],
        'execution_examples': examples or []}, expected_revision=1)['item']
    return ws, item


def sample(expected='2000'):
    return {'label': 'km to m', 'source_value': '2', 'source_unit': 'km',
        'source_representation': {'kind': 'linear'}, 'expected_value': expected}


def publish(bench, ws):
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'passed', validation
    return bench.publish(ws['id'], expected_revision=2, validation_id=validation['id'],
        expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key=ws['id'])


def test_user_contract_enters_ordinary_support_with_verified_numeric_example(bench):
    ws, prop = create_property(bench, [sample()])
    assert prop['execution_examples'] == [sample()]
    publish(bench, ws)
    release = bench.registry.load()
    binding = next(b for b in bench.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    assert binding['execution_capabilities']['normalization']['ready']
    assert binding['user_execution_ref'] in binding['dependency_refs']
    assert 'review_ref' not in binding['definition']
    assert release['definitions'][prop['property_id']].quantity_key == 'user:length'


def test_wrong_expected_number_blocks_publication(bench):
    ws, _ = create_property(bench, [sample('3')])
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'failed'
    assert any(e['code'] == 'USER_EXECUTION_EXAMPLE_FAILED' for e in validation['errors'])


def test_missing_examples_publish_native_capability(bench):
    ws, prop = create_property(bench)
    publish(bench, ws)
    support = bench.registry.support(bench.registry.load(), ['*'], 'synthetic-subject')
    binding = next(b for b in support['bindings'] if b['property_id'] == prop['property_id'])
    assert binding['execution_capabilities']['native']['ready']
    assert not binding['execution_capabilities']['normalization']['ready']

@pytest.mark.parametrize('examples,source_unit,expected,limit,logarithmic', [([sample()], 'km', '2000', 'none', False), ([], 'km', None, 'none', False), ([sample()], 'user_length', None, 'none', False), ([sample()], 'km', '2000', 'upper', False), ([{**sample('3'), 'source_value': '1'}], 'km', None, 'none', True)])
def test_ordinary_query_catalogue_admission_normalization_and_delivery(tmp_path, monkeypatch, examples, source_unit, expected, limit, logarithmic):
    import asyncio
    from uuid import uuid4
    import httpx
    from astroquery_ai.runtime import run_policy
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.runtime.scheduler import Scheduler
    from tests.rebuild.scenario import application, run_until_wait, confirmed_case
    from tests.rebuild.test_new_end_to_end import SyntheticModels, XML_HEADER
    from tests.rebuild.test_registry_normalization_flow import confirm
    monkeypatch.setattr(run_policy, 'request_policy', lambda _, preferences=None: deepcopy(run_policy.LEGACY_RUN_POLICY))

    async def run():
        from tests.rebuild.registry_fixture import make_release
        make_release(tmp_path / 'runtime' / 'synthetic-package', native_only_policy=True)
        app = application(tmp_path / 'runtime')
        original_bundle = app.registry.active_bundle()
        old, _ = await confirmed_case(app)
        with app.repository.read() as conn:
            historical = deepcopy(app.delivery.get(conn, old['task_id']))
        native_value = '-2' if logarithmic else '2'
        representation = {'kind': 'log10', 'reference_value': '1', 'reference_unit': 'm'} if logarithmic else None
        ws, prop = create_property(app.registry_workbench, examples, representation=representation)
        # Bind to the verified synthetic primary type.
        app.registry_workbench.write(ws['id'], 'bindings', {'type_id': 'pA*', 'property_key': prop['id']}, expected_revision=2)
        validation = app.registry_workbench.validate(ws['id'], expected_revision=3)['validation']
        published = app.registry_workbench.publish(ws['id'], expected_revision=3, validation_id=validation['id'],
            expected_active_bundle_id=app.registry.active_bundle()['id'], idempotency_key=ws['id'])

        class Models(SyntheticModels):
            async def json(self, *, owner, **kwargs):
                result, receipt = await super().json(owner=owner, **kwargs)
                if owner == 'M01' and kwargs['profile'].operation == 'property_selection':
                    prompt = loads(kwargs['messages'][-1]['content'])
                    pid = next(b['property_id'] for b in prompt['applicable_registry'] if b['definition']['quantity_key'] == 'user:length')
                    result['requests'][0].update(candidate_property_ids=[pid], equivalent_property_ids=[pid])
                if owner == 'M03':
                    for item in result.get('properties', []):
                        item.update(property_id=prop['property_id'], source_unit=source_unit, error_columns=['e_Length'])
                    for item in result.get('results', []):
                        item.update(property_id=prop['property_id'], value={'kind': 'real', 'value': native_value}, raw_value='<2' if limit == 'upper' else native_value, unit=source_unit, limit=limit,
                                    source_quote='SYNTHETIC_AQ 2 ' + source_unit,
                                    errors=[{'kind': 'symmetric_delta', 'values': {'delta': '0.1'}, 'raw_text': '0.1',
                                        'source_unit': source_unit, 'location': 'e_Length', 'interpretation_state': 'parsed',
                                        'role': 'unspecified', 'meaning': 'reported_error', 'reason': None}])
                return result, receipt
        app.models = Models()
        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404)
            if request.url.host == 'api.adsabs.harvard.edu':
                return httpx.Response(200, json={'response': {'numFound': 0, 'docs': []}})
            if request.url.host in {'vizier.cds.unistra.fr','vizier.idia.ac.za','vizier.cfa.harvard.edu'}:
                table = b'<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>2</TD><TD>0.1</TD></TR></TABLEDATA></DATA>' if 'Name' in request.url.params else b''
                if logarithmic:
                    table = table.replace(b'<TD>2</TD>', b'<TD>-2</TD>')
                if limit == 'upper':
                    table = table.replace(b'<TD>2</TD>', b'<TD>&lt;2</TD>')
                header = XML_HEADER.replace(b'name="Length" datatype="double"', b'name="Length" datatype="char" arraysize="*"') if limit == 'upper' else XML_HEADER
                error_header = ('<FIELD name="e_Length" datatype="double" unit="' + source_unit + '" ucd="stat.error"><DESCRIPTION>Reported error</DESCRIPTION></FIELD>').encode()
                return httpx.Response(200, content=header.replace(b'unit="m"', ('unit="' + source_unit + '"').encode()) + error_header + table + b'</TABLE></RESOURCE></VOTABLE>')
            raise AssertionError('Unexpected network request')
        app.http.transport = httpx.MockTransport(handle)
        scheduler = Scheduler(app)
        tid = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
        await run_until_wait(app, scheduler)
        state = app.view(tid)
        assert state['pending']['preview']['properties'][0]['property_id'] == prop['property_id'], state
        confirm(app, tid)
        modified = app.registry_workbench.create_workspace()['workspace']
        definition = deepcopy(prop['definition']); definition['description'] = 'User revised interpretation boundary'
        app.registry_workbench.write(modified['id'], 'properties', {'definition': definition}, item_id=prop['id'], expected_revision=1)
        latest = publish(app.registry_workbench, modified)
        newer_id = app.create('SYNTHETIC new-version draft', str(uuid4()))['task_id']
        assert app.view(newer_id)['draft']['registry_release'] == latest['bundle']['registry_ref']
        app.registry_workbench.activate(original_bundle['id'], expected_active_bundle_id=latest['bundle']['id'], idempotency_key=str(uuid4()))
        from astroquery_ai.runtime.application import Application
        from tests.rebuild.test_new_end_to_end import SyntheticIdentity
        restored = Application(tmp_path / 'runtime', allow_synthetic=True)
        restored.models, restored.identity = app.models, SyntheticIdentity(restored)
        restored.http.transport = app.http.transport
        restored.configuration.runtime['ads_api_token'] = 'SYNTHETIC-NOT-A-REAL-TOKEN'
        app, scheduler = restored, Scheduler(restored)
        while job := app.repository.claim_job(scheduler.owner_id, lease_seconds=600, task_id=tid):
            await scheduler.dispatch(job)
        state = app.view(tid)
        assert state['lifecycle'] == 'completed', state
        with app.repository.read() as conn:
            spec_ref = loads(app.repository.task(conn, tid)['query_ref'])
            spec = app.repository.object(conn, tid, 'confirmed_query', spec_ref['id'], spec_ref['version'])
            assert spec['registry_release'] == published['bundle']['registry_ref']
            delivery = app.delivery.get(conn, tid)
            assert len(delivery['measurements']) == 1, delivery
            raw = delivery['measurements'][0]
            assert raw['unit'] == source_unit and raw['value']['value'] == native_value
            assert raw['limit'] == limit
            assert raw['evidence_refs'] and raw['admission_receipt_ref']
            assert raw['uncertainty']['components'][0]['values']['delta'] == '0.1'
            assert raw['uncertainty']['components'][0]['level'] is None
            assert app.delivery.get(conn, old['task_id']) == historical
            derived = delivery['derived'][0]
            assert derived['user_execution_ref'] == spec['properties'][0]['user_execution_ref']
            assert derived['limit'] == limit
            if expected:
                from decimal import Decimal
                assert Decimal(derived['value_typed']['value']) == Decimal(expected)
                assert Decimal(derived['uncertainty_typed']['components'][0]['output_component']['values']['delta']) == Decimal('100')
            else:
                assert derived['main_state'] == 'not_run' and derived['issues']
    asyncio.run(run())


def test_user_authority_keeps_model_bounds_and_exact_builtin_guards(tmp_path):
    from dataclasses import replace
    from tests.rebuild.test_profile_scope import qualified_case
    from tests.rebuild.registry_fixture import make_release
    from astroquery_ai.registry.workspace_release import release_ref
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.runtime.errors import DomainError
    app, tid, profile, prior_spec = qualified_case(tmp_path / 'runtime')
    make_release(tmp_path / 'source')
    app.registry.import_release(tmp_path / 'source')
    ws, prop = create_property(app.registry_workbench, [sample()])
    publish(app.registry_workbench, ws)
    release = app.registry.load()
    binding = next(b for b in app.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    spec = {**prior_spec, 'registry_release': release_ref(release), 'properties': [binding]}
    with app.repository.transaction() as conn:
        qref = app.repository.put_object(conn, tid, 'confirmed_query', 'user-spec', 1, spec)
        app.repository.mutate_task(conn, tid, query_ref=canonical(qref).decode())
    result = app.profile_authority.authorize(tid, 'M03', profile, 1000)
    assert result['user_execution_refs'] == [binding['user_execution_ref']]
    assert result['authorization_origin'] == 'user_declared_local_publication'
    for changed in [replace(profile, model='unconfigured-model'), replace(profile, source_format='fits'), replace(profile, max_output_tokens=999999)]:
        with pytest.raises(DomainError):
            app.profile_authority.authorize(tid, 'M03', changed, 1000)
    # A user contract cannot widen the builtin half of a mixed selection.
    prior_spec['properties'][0]['definition']['content_sha256'] = '0' * 64
    spec['properties'].extend(prior_spec['properties'])
    with app.repository.transaction() as conn:
        qref = app.repository.put_object(conn, tid, 'confirmed_query', 'user-spec', 2, spec)
        app.repository.mutate_task(conn, tid, query_ref=canonical(qref).decode())
    with pytest.raises(DomainError) as exc:
        app.profile_authority.authorize(tid, 'M03', profile, 1000)
    assert exc.value.code == 'PROFILE_PROPERTY_NOT_VALIDATED'
    # A duplicate property ID must not inherit the sibling's user-contract exemption.
    duplicate = deepcopy(binding)
    duplicate.pop('user_execution_ref')
    duplicate['definition']['content_sha256'] = '0' * 64
    spec['properties'] = [binding, duplicate]
    with app.repository.transaction() as conn:
        qref = app.repository.put_object(conn, tid, 'confirmed_query', 'user-spec', 3, spec)
        app.repository.mutate_task(conn, tid, query_ref=canonical(qref).decode())
    with pytest.raises(DomainError) as exc:
        app.profile_authority.authorize(tid, 'M03', profile, 1000)
    assert exc.value.code == 'PROFILE_PROPERTY_NOT_VALIDATED'


def test_examples_are_bounded_and_unknown_execution_fields_rejected(bench):
    from astroquery_ai.runtime.errors import DomainError
    with pytest.raises(DomainError) as exc:
        create_property(bench, [sample()] * 21)
    assert exc.value.code == 'INVALID_EXECUTION_EXAMPLES'


@pytest.mark.parametrize('value', ['1e999999999', '9' * 129])
def test_numeric_examples_reject_unbounded_decimal_inputs(bench, value):
    example = sample(); example['source_value'] = value
    ws, _ = create_property(bench, [example])
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'failed'
    assert 'bound' in validation['execution']['properties'][next(k for k in validation['execution']['properties'] if k.startswith('property_') and validation['execution']['properties'][k]['origin'] == 'user_defined')]['validation']['examples'][0]['detail'].lower()


def test_native_binding_override_uses_user_contract_but_original_keeps_review(bench):
    ws = bench.create_workspace()['workspace']
    prop = bench.list_items('properties')['items'][0]
    original = next(b for b in bench.list_items('bindings')['items'] if b['type_id'] == '*')
    bench.write(ws['id'], 'bindings', {'conditions': [{'otype': '*'}]}, item_id=original['id'], expected_revision=1)
    publish(bench, ws)
    support = bench.registry.support(bench.registry.load(), ['*'], 'synthetic-subject')
    assert len(support['bindings']) == 1
    assert support['bindings'][0]['user_execution_ref']
    assert not support['bindings'][0]['execution_capabilities']['normalization']['ready']
    assert support['bindings'][0]['definition'] == prop['definition']


def test_published_contract_tamper_and_frozen_binding_tamper_are_rejected(bench):
    from types import SimpleNamespace
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.registry.user_execution import verified_user_bindings
    from astroquery_ai.registry.workspace_release import release_ref
    ws, prop = create_property(bench, [sample()]); publish(bench, ws)
    release = bench.registry.load()
    binding = next(b for b in bench.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    spec = {'registry_release': release_ref(release), 'properties': [binding]}
    app = SimpleNamespace(registry=bench.registry)
    assert verified_user_bindings(app, spec) == {prop['property_id']}
    binding['execution_capabilities']['normalization']['ready'] = False
    with pytest.raises(DomainError, match='contract'):
        verified_user_bindings(app, spec)
    # Rehashing the envelope cannot make fabricated validation outcomes true.
    from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads
    directory = bench.registry.root / 'releases' / release['manifest']['release_id']
    payload = loads((directory / 'workspace.json').read_bytes())
    entry = next(iter(payload['execution_manifest']['contracts'].values()))
    entry['contract']['capabilities']['normalization']['ready'] = False
    manifest = loads((directory / 'manifest.json').read_bytes())
    manifest['workspace_sha256'] = digest(payload); manifest['content_sha256'] = content_hash(manifest)
    (directory / 'workspace.json').write_bytes(canonical(payload)); (directory / 'manifest.json').write_bytes(canonical(manifest))
    with pytest.raises(DomainError):
        bench.registry.load(release['manifest']['release_id'])


def test_legacy_workspace_without_execution_manifest_keeps_old_exclusion(bench, tmp_path):
    from astroquery_ai.runtime.codec import canonical, content_hash, digest
    ws, prop = create_property(bench, [sample()]); publish(bench, ws)
    release = bench.registry.load()
    payload = deepcopy(release['workspace']); payload.pop('execution_manifest')
    manifest = deepcopy(release['manifest']); manifest['workspace_sha256'] = digest(payload)
    manifest['content_sha256'] = content_hash(manifest)
    directory = tmp_path / 'historical-workspace'; directory.mkdir()
    (directory / 'workspace.json').write_bytes(canonical(payload)); (directory / 'manifest.json').write_bytes(canonical(manifest))
    legacy = bench.registry.validate(directory)
    support = bench.registry.support(legacy, ['*'], 'synthetic-subject')
    assert all(b['property_id'] != prop['property_id'] for b in support['bindings'])
    assert any(g['property_id'] == prop['property_id'] for g in support['gaps'])


def test_exact_profile_examples_and_edit_invalidation(bench):
    from astroquery_ai.registry.workbench_projection import ref
    from astroquery_ai.runtime.errors import DomainError
    ws, prop = create_property(bench, [sample()])
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    profiles = deepcopy(prop['output_profiles'])
    profiles[0]['unit']['canonical_symbol'] = 'cm'
    example = sample('200000'); example['profile_ref'] = ref(prop['output_profiles'][0], 'profile')
    written = bench.write(ws['id'], 'properties', {'execution_examples': [example], 'output_profiles': profiles},
                         item_id=prop['id'], expected_revision=2)['item']
    assert written['execution_examples'][0]['profile_ref'] == ref(written['output_profiles'][0], 'profile')
    with pytest.raises(DomainError) as exc:
        bench.publish(ws['id'], expected_revision=3, validation_id=validation['id'],
                      expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='stale-contract')
    assert exc.value.code == 'VALIDATION_REQUIRED'
    validation = bench.validate(ws['id'], expected_revision=3)['validation']
    assert validation['state'] == 'passed'
    assert validation['execution']['properties'][prop['id']]['validation']['examples'][0]['actual_value'] == '200000'


def test_contract_freezes_exact_dictionary_and_applicability_dependencies(bench):
    ws, prop = create_property(bench, [sample()]); publish(bench, ws)
    release = bench.registry.load()
    entry = next(iter(release['workspace']['execution_manifest']['contracts'].values()))
    contract = entry['contract']
    assert {'synthetic-family', 'synthetic-subject', 'synthetic-whole'} <= {r['id'] for r in contract['dictionary_refs']}
    assert contract['applicability_type_refs'][0]['id'] == '*'
    binding = next(b for b in bench.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    assert all(r in binding['dependency_refs'] for r in contract['dictionary_refs'] + contract['applicability_type_refs'])


def test_server_owned_user_policy_is_separate_from_source_scientific_policy(bench):
    policies = bench.summary()['capabilities']['conversion_policies']
    policy = next((p for p in policies if p.get('user_declared')), None)
    assert policy is not None
    assert policy['policy_id'] == 'user-declared-same-quantity'
    assert not policy.get('review_ref')
    ws, prop = create_property(bench)
    profiles = deepcopy(prop['output_profiles'])
    profiles[0]['conversion_policy_ref'] = {'id': policy['policy_id'], 'version': policy['version'], 'content_sha256': policy['content_sha256']}
    bench.write(ws['id'], 'properties', {'output_profiles': profiles, 'execution_examples': [sample()]}, item_id=prop['id'], expected_revision=2)
    validation = bench.validate(ws['id'], expected_revision=3)['validation']
    assert validation['state'] == 'passed'
    bench.publish(ws['id'], expected_revision=3, validation_id=validation['id'],
                  expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='local-policy')
    release = bench.registry.load()
    assert policy in release['data']['conversion-policies']
    contract = next(iter(release['workspace']['execution_manifest']['contracts'].values()))['contract']
    assert contract['local_conversion_policy'] == policy


def test_user_contract_cannot_widen_global_composition_exclusion(bench):
    ws, _ = create_property(bench, [sample()]); publish(bench, ws)
    release = deepcopy(bench.registry.load())
    release['base_release']['compiled']['exclusions'] = [{'otype': '*'}]
    support = bench.registry.support(release, ['*'], 'synthetic-subject')
    assert support['bindings'] == []
    assert any(g['reason'] == 'excluded_composition' for g in support['gaps'])


def test_inline_profile_sample_grants_only_its_exact_binding(bench):
    from astroquery_ai.registry.workbench_projection import ref
    ws, prop = create_property(bench, [sample()])
    inline = deepcopy(prop['output_profiles'][0]); inline['unit']['canonical_symbol'] = 'cm'
    saved = bench.write(ws['id'], 'bindings', {'type_id': 'pA*', 'property_key': prop['id'], 'output_profile': inline}, expected_revision=2)['item']
    examples = [sample(), {**sample('200000'), 'profile_ref': saved['profile_ref']}]
    bench.write(ws['id'], 'properties', {'execution_examples': examples}, item_id=prop['id'], expected_revision=3)
    validation = bench.validate(ws['id'], expected_revision=4)['validation']
    assert validation['state'] == 'passed', validation
    bench.publish(ws['id'], expected_revision=4, validation_id=validation['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='inline')
    release = bench.registry.load()
    shared = next(b for b in bench.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    scoped = next(b for b in bench.registry.support(release, ['pA*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    assert shared['execution_capabilities']['normalization']['ready']
    assert scoped['execution_capabilities']['normalization']['ready']
    assert ref(scoped['output_profile'], 'profile') == saved['profile_ref']
    # Editing that scoped output invalidates only its exact example target.
    later = bench.create_workspace()['workspace']
    inline['unit']['canonical_symbol'] = 'mm'
    bench.write(later['id'], 'bindings', {'output_profile': inline}, item_id=saved['id'], expected_revision=1)
    validation = bench.validate(later['id'], expected_revision=2)['validation']
    assert validation['state'] == 'failed'
    assert any(e['code'] == 'USER_EXECUTION_EXAMPLE_FAILED' for e in validation['errors'])


def test_unvalidated_output_does_not_borrow_sibling_examples(bench):
    ws, prop = create_property(bench, [sample()])
    inline = deepcopy(prop['output_profiles'][0]); inline['unit']['canonical_symbol'] = 'cm'
    bench.write(ws['id'], 'bindings', {'type_id': 'pA*', 'property_key': prop['id'], 'output_profile': inline}, expected_revision=2)
    validation = bench.validate(ws['id'], expected_revision=3)['validation']
    assert validation['state'] == 'passed'
    bench.publish(ws['id'], expected_revision=3, validation_id=validation['id'], expected_active_bundle_id=bench.registry.active_bundle()['id'], idempotency_key='sibling')
    release = bench.registry.load()
    shared = next(b for b in bench.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    scoped = next(b for b in bench.registry.support(release, ['pA*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    assert shared['execution_capabilities']['normalization']['ready']
    assert not scoped['execution_capabilities']['normalization']['ready']


def test_source_specific_policy_is_never_silently_replaced(tmp_path):
    from tests.rebuild.registry_fixture import make_release
    from astroquery_ai.runtime.application import Application
    app = Application(tmp_path / 'runtime', allow_synthetic=True)
    make_release(tmp_path / 'source', native_only_policy=True)
    app.registry.import_release(tmp_path / 'source')
    bench = app.registry_workbench
    source = bench.list_items('properties')['items'][0]
    ws, prop = create_property(bench, [sample()])
    profiles = deepcopy(prop['output_profiles'])
    profiles[0]['conversion_policy_ref'] = source['output_profiles'][0]['conversion_policy_ref']
    bench.write(ws['id'], 'properties', {'output_profiles': profiles}, item_id=prop['id'], expected_revision=2)
    validation = bench.validate(ws['id'], expected_revision=3)['validation']
    assert validation['state'] == 'failed'
    assert any(e['code'] == 'USER_EXECUTION_EXAMPLE_FAILED' and '用户声明' in e['message'] for e in validation['errors'])


def test_declared_dimension_must_match_the_parsed_new_unit(bench):
    ws, _ = create_property(bench, [{**sample('2'), 'source_unit': 'kg'}], unit={'canonical_symbol': 'kg', 'dimension': 'length'})
    validation = bench.validate(ws['id'], expected_revision=2)['validation']
    assert validation['state'] == 'failed'
    assert any(e['code'] == 'UNIT_DIMENSION_CONFLICT' for e in validation['errors'])


def test_user_property_paper_admission_uses_actual_page_evidence(bench):
    from astroquery_ai.runtime.codec import digest
    from astroquery_ai.science.extraction import EvidenceExtractor, MeasurementProposal
    from astroquery_ai.science.paper_admission import AdmissionCheck, check_local_evidence
    from tests.rebuild.test_paper_admission import paper_proposal
    from tests.rebuild.factories import ref
    ws, prop = create_property(bench, [sample()]); publish(bench, ws)
    binding = next(b for b in bench.registry.support(bench.registry.load(), ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
    target = {'target_id': 'SYNTHETIC target', 'main_id': 'SYNTHETIC_AQ', 'aliases': []}
    data = paper_proposal().model_dump(mode='json')
    text = 'SYNTHETIC_AQ has a measured whole length of 2 km.'
    data.update(property_id=prop['property_id'], raw_value='2', value={'kind': 'real', 'value': '2'},
                unit='km', errors=[], location_kind='body', source_quote=text)
    proposal = MeasurementProposal.model_validate(data)
    anchor = {'page': 3, 'quote': text}
    check = AdmissionCheck.model_validate({'index': 0, 'subject': 'target', 'printed_subject': 'SYNTHETIC_AQ',
        'subject_evidence': [anchor], 'result_role': 'reported_result', 'role_evidence': [anchor],
        'quantity_match': 'exact', 'quantity_evidence': [anchor], 'unit_match': 'exact',
        'native_unit': 'km', 'unit_evidence': [anchor], 'reason': 'SYNTHETIC literal page evidence'})
    verified = check_local_evidence(proposal, check, target, {3: text}, {}, require_quantity=True,
                                   require_units=True, property_binding=binding)
    assert verified['state'] == 'passed', verified
    assert verified['proposal_hash'] == digest(proposal.model_dump(mode='json'))
    spec = {'task_id': 'SYNTHETIC task', 'spec_id': 'SYNTHETIC spec', 'target': target, 'properties': [binding]}
    result = EvidenceExtractor(None).assemble(spec=spec, source={'source_id': 'SYNTHETIC paper', 'kind': 'paper', 'qualification_ref': ref()},
        artifact={'artifact_id': 'SYNTHETIC artifact', 'sha256': ref()['content_sha256']}, proposal=proposal,
        owner='M06', batch_id='SYNTHETIC batch', allowed_pages=[3], paper_verification=verified)
    assert result['state'] == 'admitted', result
    assert result['measurement']['unit'] == 'km'
    assert result['measurement']['property_ref'] == prop['definition_ref']
    missing = check_local_evidence(proposal, check, target, {3: 'Unrelated page'}, {},
                                  require_quantity=True, require_units=True, property_binding=binding)
    assert missing['state'] != 'passed'


@pytest.mark.parametrize('historical_property_report', [False, True])
def test_current_query_policy_missing_author_knowledge_preserves_user_facts(tmp_path, monkeypatch, historical_property_report):
    import asyncio
    from uuid import uuid4
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.runtime.scheduler import Scheduler
    from astroquery_ai.science.property_insights import unpack_materials
    from tests.rebuild.scenario import application, run_until_wait, synthetic_author_manifest
    from tests.rebuild.test_registry_normalization_flow import confirm
    from tests.rebuild.test_new_end_to_end import SyntheticModels

    if historical_property_report:
        from astroquery_ai.runtime import run_policy
        current_policy = run_policy.request_policy
        def historical_policy(*args, **kwargs):
            policy = current_policy(*args, **kwargs)
            policy['insights'].update(presentation='research-property/1', final_model='qwen3.8-max')
            return policy
        # Keep the previous frozen property-report contract covered alongside
        # the newly published ordinary material-summary presentation.
        monkeypatch.setattr(run_policy, 'request_policy', historical_policy)

    async def run():
        app = application(tmp_path / 'runtime')
        ws, prop = create_property(app.registry_workbench, [sample()])
        app.registry_workbench.write(ws['id'], 'bindings', {'type_id': 'pA*', 'property_key': prop['id']}, expected_revision=2)
        validation = app.registry_workbench.validate(ws['id'], expected_revision=3)['validation']
        app.registry_workbench.publish(ws['id'], expected_revision=3, validation_id=validation['id'],
            expected_active_bundle_id=app.registry.active_bundle()['id'], idempotency_key='normal-policy')
        manifest = synthetic_author_manifest(app)
        app.knowledge.load = lambda reference=None: {'manifest': manifest, 'sources': {}, 'entries': {},
            'data': {'bindings': []}, 'author': {'sources': [], 'entries': [], 'bindings': []}}
        app.configuration.runtime.update(retrieval_policy_version='retrieval-feedback/1', research_delivery_version='research-delivery/1')
        calls = []
        class Models(SyntheticModels):
            async def json(self, *, owner, **kwargs):
                version = kwargs['profile'].version; body = loads(kwargs['messages'][-1]['content'])
                if version == 'shared-verified-literature-names/1':
                    label = next(iter(body['verified_names']))
                    return {'search_names': [{'source_names': [label], 'text': body['verified_names'][label], 'basis': 'SYNTHETIC exact identity'}], 'ambiguities': []}, {'attempt_id': 'synthetic-names'}
                if version == 'feedback-quantity-planning/1':
                    return {'direct_expression': 'length', 'quantity_field': 'abs', 'method_expression': None,
                        'intent': 'SYNTHETIC length', 'change_reason': 'SYNTHETIC initial', 'rewrite_useful': False}, {'attempt_id': 'synthetic-planning'}
                if version == 'unified-catalog-quality-2':
                    return {'items': [{'item_id': r['item_id'], 'subject': 'target', 'quantity_relation': 'same',
                        'reported_quantity': 'SYNTHETIC whole length', 'subject_scale': 'whole', 'result_role': 'reported_result',
                        'native_representation': 'linear', 'value_match': 'exact', 'unit_match': 'exact', 'errors_match': 'not_reported',
                        'evidence_columns': ['Length'], 'checked_ids': list(body['source_materials'])[:1],
                        'caution_ids': [], 'review_issue': None, 'reason': 'SYNTHETIC source'} for r in body['items']]}, {'attempt_id': 'synthetic-quality'}
                if owner == 'M11':
                    calls.append(version)
                    if version == 'material-summary/1':
                        assert not historical_property_report
                        assert all(item['knowledge_background'] == [] for item in body['properties'])
                        return {item['label']: '原始资料保留了目标的长度测量和观测方法。' for item in body['properties']}, {
                            'attempt_id': 'synthetic-user-summary', 'model': 'qwen3.8-flash'}
                    material = unpack_materials(body)
                    assert material['knowledge'] == []
                    row = material['record_index'][0]
                    entry = {'text': '原始来源数据已保留，作者知识尚未覆盖此性质。',
                        'measurement_ids': [row['measurement_id']], 'evidence_ids': row['evidence_ids'][:1], 'claim_ids': []}
                    return {'found': [entry], 'comparison': [], 'uses': [], 'limitations': [], 'findings': []}, {'attempt_id': 'synthetic-user-facts', 'model': 'qwen3.8-max'}
                result, receipt = await super().json(owner=owner, **kwargs)
                if owner == 'M01' and kwargs['profile'].operation == 'property_selection':
                    pid = next(b['property_id'] for b in body['applicable_registry'] if b['definition']['quantity_key'] == 'user:length')
                    result['requests'][0].update(candidate_property_ids=[pid], equivalent_property_ids=[pid])
                if owner == 'M03':
                    for item in result.get('properties', []) + result.get('results', []):
                        item['property_id'] = prop['property_id']
                return result, receipt
        app.models = Models(); scheduler = Scheduler(app)
        tid = app.create('SYNTHETIC_AQ 测试长度', str(uuid4()))['task_id']
        await run_until_wait(app, scheduler); confirm(app, tid)
        await run_until_wait(app, scheduler)
        assert app.view(tid)['lifecycle'] == 'completed'
        with app.repository.read() as conn:
            spec = app.repository.objects(conn, tid, 'confirmed_query')[0]
            assert spec['run_policy']['insights']['mode'] == 'dot_author/1'
            assert spec['run_policy']['workflow_contract'] == 'backend-consolidation/1'
            delivery = app.delivery.get(conn, tid)
            assert len(delivery['measurements']) == 1
            assert delivery['derived'][0]['main_state'] == 'ready'
            if historical_property_report:
                assert delivery['insight_report']['schema_version'] == 'InsightReport/4'
                assert delivery['insight_report']['knowledge_coverage']['missing'] == 1
                assert delivery['insight_report']['cards'][0]['knowledge_coverage']['state'] == 'missing'
            else:
                assert spec['run_policy']['insights']['presentation'] == 'research-workbench/2'
                assert spec['knowledge_context_ref']['content_sha256']
                assert delivery['insight_report']['schema_version'] == 'InsightBundle/1'
                assert delivery['insight_report']['knowledge_context_ref'] == spec['knowledge_context_ref']
                assert delivery['insight_report']['material_report']['counts'][prop['property_id']]['ready'] == 1
                property_report = delivery['insight_report']['property_report']
                assert property_report['knowledge_coverage']['missing'] == 1
                assert property_report['cards'][0]['knowledge_coverage']['state'] == 'missing'
                summary, = app.repository.objects(conn, tid, 'material_summary')
                assert summary['property_id'] == prop['property_id'] and summary['state'] == 'ready'
                assert summary['basis']['knowledge'] == []
            assert calls
    asyncio.run(run())


def test_validation_capabilities_refresh_without_a_draft_edit(bench):
    ws, prop = create_property(bench, [sample()])
    before = bench.detail('properties', prop['id'], workspace_id=ws['id'])
    assert before['execution_capabilities']['validation']['state'] == 'pending'
    bench.validate(ws['id'], expected_revision=2)
    after = bench.detail('properties', prop['id'], workspace_id=ws['id'])
    assert after['execution_capabilities']['validation']['state'] == 'passed'

@pytest.mark.parametrize('kind,native_only,source_mode', [('log10', False, 'absent'), ('log10', True, 'absent'), ('ln', True, 'absent'), ('magnitude', True, 'absent'), ('log10', True, 'native_unknown'), ('magnitude', True, 'native_unknown'), ('log10', False, 'known')])
def test_user_normalization_never_invents_a_missing_nonlinear_source_reference(tmp_path, kind, native_only, source_mode):
    import asyncio
    from types import SimpleNamespace
    from astroquery_ai.runtime.application import Application
    from astroquery_ai.runtime.codec import canonical, content_hash
    from astroquery_ai.registry.workspace_release import release_ref
    from astroquery_ai.science.processing.normalization import normalize
    from tests.rebuild.registry_fixture import make_release
    from tests.rebuild.factories import measurement

    async def run():
        app = Application(tmp_path / 'runtime', allow_synthetic=True)
        make_release(tmp_path / 'package'); app.registry.import_release(tmp_path / 'package')
        bench, repo = app.registry_workbench, app.repository
        target = {'kind': kind, **({'native_coordinate_only': True} if native_only else
                   {'reference_value': '1000', 'reference_unit': 'm'})}
        examples = [] if native_only else [{**sample('2'), 'source_value': '100000', 'source_unit': 'm'}]
        ws, prop = create_property(bench, examples, representation=target); publish(bench, ws)
        release = app.registry.load()
        binding = next(b for b in app.registry.support(release, ['*'], 'synthetic-subject')['bindings'] if b['property_id'] == prop['property_id'])
        tid = repo.create_task('SYNTHETIC user source reference regression')['task_id']
        record = measurement(pid=prop['property_id'], value='2')
        record.update(task_id=tid, unit='dex' if kind == 'log10' else 'mag' if kind == 'magnitude' else '1',
                      representation=kind, property_ref=prop['definition_ref'])
        spec = {'properties': [binding], 'registry_release': release_ref(release), 'dependencies': binding['dependency_refs']}
        known = source_mode == 'known'
        quote = 'SYNTHETIC reported log10(length / 1000 m) = 2.' if known else 'SYNTHETIC reported nonlinear length 2; its source reference is not specified.'
        source_parameters = deepcopy(target) if source_mode in {'known', 'native_unknown'} else None
        artifact = app.artifacts.write(quote.encode(), 'text/plain')
        originals = {'context': {'snapshot_binding': {'property': record['property_ref']},
                                'measurement_ref': {'id': record['measurement_id'], 'version': 1}},
            'source': {'kind': 'paper'}, 'admission': {'status': 'passed'},
            'interpretation': {'proposal': {'representation_parameters': source_parameters, 'source_quote': quote},
                               'paper_verification': {'state': 'passed'}},
            'evidence': {'artifact_ref': {'id': artifact['artifact_id'], 'content_sha256': artifact['sha256']}}}
        with repo.transaction() as conn:
            app.artifacts.register(conn, tid, 'source', artifact)
            query = repo.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC query', 1, spec)
            repo.mutate_task(conn, tid, lifecycle='queued', science_state='open', query_ref=canonical(query).decode())
            for name, obj in originals.items():
                reference = repo.put_object(conn, tid, name, name, 1, obj)
                field = {'admission': 'admission_receipt_ref', 'evidence': 'evidence_refs'}.get(name, name + '_ref')
                record[field] = [reference] if name == 'evidence' else reference
            record['content_sha256'] = content_hash(record)
            repo.put_object(conn, tid, 'measurement', record['measurement_id'], 1, record)
            repo.enqueue(conn, tid, 'M08', 'normalize', {'measurement_id': record['measurement_id'], 'source_hash': record['content_sha256']})
        service = SimpleNamespace(repo=repo, app=app, spec=lambda *args: spec, _error_receipt=lambda *args: None)
        await normalize(service, repo.claim_job('SYNTHETIC worker'))
        with repo.read() as conn:
            result = repo.objects(conn, tid, 'derived')[0]
            assert result['main_state'] == ('ready' if known else 'not_run')
            if known:
                assert result['value_typed']['value'] == '2'
            else:
                assert result['issues'][0]['code'] == 'user_source_representation_reference_unresolved'
            assert repo.object(conn, tid, 'measurement', record['measurement_id']) == record
            assert repo.objects(conn, tid, 'processing_receipt')[0]['processing_state'] == ('succeeded' if known else 'not_run')
            assert not repo.objects(conn, tid, 'science_condition_check')
    asyncio.run(run())


def test_legacy_published_view_does_not_fabricate_execution_capabilities(bench, tmp_path, monkeypatch):
    from astroquery_ai.runtime.codec import canonical, content_hash, digest
    ws, prop = create_property(bench); publish(bench, ws)
    release = bench.registry.load(); payload = deepcopy(release['workspace']); payload.pop('execution_manifest')
    manifest = deepcopy(release['manifest']); manifest.update(release_id='SYNTHETIC-legacy', workspace_sha256=digest(payload))
    manifest['content_sha256'] = content_hash(manifest)
    directory = tmp_path / 'legacy'; directory.mkdir()
    (directory / 'workspace.json').write_bytes(canonical(payload)); (directory / 'manifest.json').write_bytes(canonical(manifest))
    legacy = bench.registry.validate(directory)
    original = bench.registry.load
    monkeypatch.setattr(bench.registry, 'load', lambda identifier=None: legacy if identifier == 'SYNTHETIC-legacy' else original(identifier))
    view = bench.detail('properties', prop['id'], release_id='SYNTHETIC-legacy')
    assert not view.get('execution_capabilities', {}).get('extraction', {}).get('ready')
    assert 'execution_ref' not in view.get('execution_capabilities', {})
    assert all(b['property_id'] != prop['property_id'] for b in bench.registry.support(legacy, ['*'], 'synthetic-subject')['bindings'])


def test_published_capabilities_are_frozen_not_recompiled_by_workbench(bench, monkeypatch):
    from astroquery_ai.registry import user_execution
    ws, prop = create_property(bench, [sample()]); publish(bench, ws)
    release = bench.registry.load()
    entry = next(iter(release['workspace']['execution_manifest']['contracts'].values()))
    expected = {**entry['contract']['capabilities'], 'execution_ref': entry['reference']}
    # Loading the immutable package is already verified; changing the draft compiler
    # cannot alter this published view. A draft still uses the current compiler.
    monkeypatch.setattr(bench.registry, 'load', lambda identifier=None: release)
    def fail(*args):
        raise AssertionError('published presentation must read frozen capabilities')
    monkeypatch.setattr(user_execution, 'compile_execution', fail)
    view = bench.detail('properties', prop['id'])
    assert view['execution_capabilities'] == expected
