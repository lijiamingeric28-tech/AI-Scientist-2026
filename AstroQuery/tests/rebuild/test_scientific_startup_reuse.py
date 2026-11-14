"""Synthetic startup reuse counterexamples; never scientific approval receipts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from itertools import product
import lzma
from threading import Barrier

import pytest

from astroquery_ai.registry.assembly import finite_support
from astroquery_ai.registry.candidate import CandidateRegistry
from astroquery_ai.registry.consumer import compile_verified_inputs
from astroquery_ai.registry.projection import CandidateProjection
from astroquery_ai.registry.science_conditions import reindex_conditions
from astroquery_ai.registry.service import RegistryService
from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.registry_fixture import make_release


def synthetic_candidate(tmp_path, count=2):
    data = make_release(tmp_path / 'synthetic-source')
    definition = data['definitions'][0]
    definition['measurement_conditions_schema'] = [{'key': 'band', 'value_type': 'text',
        'required': True, 'missing_handling': 'cannot_bind_quantity'}]
    definition['content_sha256'] = content_hash(definition)
    profile = data['output-profiles'][0]
    profile['representation'].update(multiplier='1', offset='0')
    profile['content_sha256'] = content_hash(profile)
    types = ['T' + str(i) for i in range(count)]
    subject = definition['subject_class_id']
    def ref(value, key, version='version'):
        return {'id': value[key], 'version': value[version], 'content_sha256': value['content_sha256']}
    rule = {'rule_id': 'synthetic-rule', 'version': 1, 'kind': 'include',
        'when': {'any_of': [{'otype': t} for t in types]}, 'subject_class_id': subject,
        'definition_ref': ref(definition, 'property_id', 'definition_version'),
        'profile_ref': ref(profile, 'profile_id')}
    rule['content_sha256'] = content_hash(rule)
    record = {'record_id': 'synthetic-science', 'version': 1,
        'definition_ref': rule['definition_ref'], 'profile_ref': rule['profile_ref'],
        'required_conditions': [], 'operations': [],
        'context_contracts': [{'key': 'band', 'required_scope': 'all_sources'}]}
    record['content_sha256'] = content_hash(record)
    science = reindex_conditions({'config': {}, 'records': {definition['property_id']: record},
        'variants': {definition['property_id']: [{'accepted_otypes': types, 'record': record}]}})
    return {'report': {'manifest_content_sha256': 'a' * 64}, 'science': science, 'data': {
        **{new: data[old] for new, old in [('definitions', 'definitions'), ('output_profiles', 'output-profiles'),
            ('conversion_policies', 'conversion-policies'), ('families', 'families'),
            ('subject_classes', 'subject-classes'), ('object_scales', 'object-scales'),
            ('evidence', 'evidence'), ('reviews', 'reviews')]},
        'type_profiles': [{'otype': t, 'subject_class_id': subject} for t in types],
        'unapproved_aggregate_composition_and_rules': {'rules': [rule]},
        'build_only_symbolic_support': finite_support([rule])}}


def compile_candidate(candidate):
    return compile_verified_inputs(candidate, 'a' * 64, 'b' * 64, None, 'reviewed-AST-context/2')


def test_release_compilation_builds_exact_reference_indexes_once(tmp_path, monkeypatch):
    """Rebuilding whole-package reference indexes for each context is the regression."""
    import astroquery_ai.registry.amendments as amendments
    candidate = synthetic_candidate(tmp_path, count=40)
    real = amendments.reference_key
    calls = []
    def counted(ref):
        calls.append(ref)
        return real(ref)
    monkeypatch.setattr(amendments, 'reference_key', counted)
    result = compile_candidate(candidate)
    assert len(result['context_bindings']) == 40
    assert len(calls) <= 20


def test_repeated_projection_validates_each_exact_model_once(tmp_path, monkeypatch):
    from astroquery_ai.registry.models import PropertyDefinition, OutputProfile
    candidate = synthetic_candidate(tmp_path)
    support = CandidateRegistry().select_context(candidate, accepted_otypes=['T0'],
        subject_class_id='synthetic-subject')
    projection = CandidateProjection(candidate)
    calls = {'definition': 0, 'profile': 0}
    for name, model in [('definition', PropertyDefinition), ('profile', OutputProfile)]:
        original = model.model_validate
        def counted(value, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(value, **kwargs)
        monkeypatch.setattr(model, 'model_validate', counted)
    first = projection.support(support)
    first['bindings'][0]['definition']['aliases'].append('caller mutation')
    first['bindings'][0]['output_profile']['representation']['scale'] = '99'
    second = projection.support(support)
    assert 'caller mutation' not in second['bindings'][0]['definition']['aliases']
    assert second['bindings'][0]['output_profile']['representation']['scale'] == '1'
    assert calls == {'definition': 1, 'profile': 1}


def test_projection_key_covers_science_profile_source_review_and_protocol(tmp_path):
    candidate = synthetic_candidate(tmp_path)
    definition = candidate['data']['definitions'][0]
    profile = candidate['data']['output_profiles'][0]
    projection = CandidateProjection(candidate)
    original = projection.definition(definition, profile)
    candidate['science']['variants'][definition['property_id']][0]['record']['context_contracts'][0]['required_scope'] = 'error_sources'
    scoped = projection.definition(definition, profile)
    assert scoped['measurement_conditions_schema'][0]['required_scope'] == 'error_sources'
    assert scoped['content_sha256'] != original['content_sha256']
    other_profile = {**profile, 'content_sha256': 'c' * 64}
    assert projection.definition(definition, other_profile)['measurement_conditions_schema'][0]['required_scope'] == 'all_sources'
    definition['aliases'].append('changed source without updating its claimed hash')
    assert 'changed source without updating its claimed hash' in projection.definition(definition, profile)['aliases']
    definition['review_ref'] = {'review_id': candidate['data']['reviews'][0]['review_id'], 'version': 1}
    projection.definition(definition, profile)
    projection.reviews[(definition['review_ref']['review_id'], '1')]['decision'] = 'corrupt'
    with pytest.raises(DomainError) as caught:
        projection.definition(definition, profile)
    assert caught.value.code == 'CANDIDATE_REVIEW_REFERENCE'


def test_profile_key_includes_full_source_and_protocol(tmp_path, monkeypatch):
    from astroquery_ai.registry.models import OutputProfile
    candidate = synthetic_candidate(tmp_path)
    source = candidate['data']['output_profiles'][0]
    projection = CandidateProjection(candidate)
    original = OutputProfile.model_validate
    calls = []
    def counted(value, **kwargs):
        calls.append(1)
        return original(value, **kwargs)
    monkeypatch.setattr(OutputProfile, 'model_validate', counted)
    first = projection.profile(source)
    source['representation']['multiplier'] = '2'
    second = projection.profile(source)
    assert second['representation']['scale'] == '2'
    assert first['content_sha256'] != second['content_sha256']
    projection.version = 'synthetic-next-protocol'
    projection.profile(source)
    assert len(calls) == 3


def test_failed_projection_is_not_memoized_and_retries_current_input(tmp_path):
    candidate = synthetic_candidate(tmp_path)
    source = candidate['data']['output_profiles'][0]
    projection = CandidateProjection(candidate)
    del source['representation']['multiplier']
    for _ in range(2):
        with pytest.raises(DomainError) as caught:
            projection.profile(source)
        assert caught.value.code == 'CANDIDATE_LINEAR_PARAMETERS'
    source['representation']['multiplier'] = '3'
    assert projection.profile(source)['representation']['scale'] == '3'


def test_definition_memo_ignores_audit_fields_that_do_not_affect_projection(tmp_path, monkeypatch):
    """Rehashing/revalidating whole science audit bodies must not scale with contexts."""
    from astroquery_ai.registry.models import PropertyDefinition
    candidate = synthetic_candidate(tmp_path)
    definition = candidate['data']['definitions'][0]
    profile = candidate['data']['output_profiles'][0]
    projection = CandidateProjection(candidate)
    real = PropertyDefinition.model_validate
    calls = []
    def counted(value, **kwargs):
        calls.append(1)
        return real(value, **kwargs)
    monkeypatch.setattr(PropertyDefinition, 'model_validate', counted)
    first = projection.definition(definition, profile)
    candidate['science']['variants'][definition['property_id']][0]['record']['audit_history'] = ['large audit body' * 1000]
    second = projection.definition(definition, profile)
    assert second == first
    assert len(calls) == 1


def test_context_discovery_does_not_recheck_already_declared_subjects(tmp_path, monkeypatch):
    import astroquery_ai.registry.compiler as compiler
    import astroquery_ai.registry.candidate as candidate_module
    candidate = synthetic_candidate(tmp_path, count=40)
    real = compiler.matches
    calls = {'discovery': 0, 'selection': 0}
    def discovery(*args):
        calls['discovery'] += 1
        return real(*args)
    def selection(*args):
        calls['selection'] += 1
        return real(*args)
    monkeypatch.setattr(compiler, 'matches', discovery)
    monkeypatch.setattr(candidate_module, 'matches', selection)
    assert len(compile_candidate(candidate)['context_bindings']) == 40
    assert calls == {'discovery': 0, 'selection': 40}


def test_context_discovery_still_validates_unused_source_conditions(tmp_path):
    candidate = synthetic_candidate(tmp_path)
    rule = deepcopy(candidate['data']['unapproved_aggregate_composition_and_rules']['rules'][0])
    rule.update(rule_id='unused-invalid', when={'unsupported': 'invalid'})
    candidate['data']['unapproved_aggregate_composition_and_rules']['rules'].append(rule)
    with pytest.raises(DomainError) as caught:
        compile_candidate(candidate)
    assert caught.value.code == 'UNKNOWN_COMPOSITION_OPERATOR'


def test_compilation_hashes_the_complete_context_payload_once(tmp_path, monkeypatch):
    import astroquery_ai.registry.consumer as consumer
    candidate = synthetic_candidate(tmp_path)
    real = consumer.digest
    calls = []
    def counted(value):
        if isinstance(value, dict) and "('T0', 'synthetic-subject')" in value:
            calls.append(1)
        return real(value)
    monkeypatch.setattr(consumer, 'digest', counted)
    assert compile_candidate(candidate)['manifest']['consumer_view_hash'] == 'f24cf2b52d2d5bd04bcb378b4e83c791fb7589251c1c3f66f8da25bf097ef293'
    assert len(calls) == 1


def test_first_projection_copies_sources_once_without_redundant_deepcopy(tmp_path, monkeypatch):
    import astroquery_ai.registry.projection as module
    candidate = synthetic_candidate(tmp_path)
    definition = candidate['data']['definitions'][0]
    profile = candidate['data']['output_profiles'][0]
    original_definition, original_profile = deepcopy(definition), deepcopy(profile)
    real = module.deepcopy
    copied_sources = []
    def counted(value):
        if value is definition or value is profile:
            copied_sources.append(value)
        return real(value)
    monkeypatch.setattr(module, 'deepcopy', counted)
    projection = CandidateProjection(candidate)
    d = projection.definition(definition, profile)
    p = projection.profile(profile)
    d['explanation']['distinctions'].append('caller mutation')
    p['unit']['canonical_symbol'] = 'changed'
    assert definition == original_definition
    assert profile == original_profile
    assert copied_sources == []


def test_prepared_index_does_not_mix_same_id_different_versions(tmp_path):
    candidate = synthetic_candidate(tmp_path)
    data = candidate['data']
    first_rule = data['unapproved_aggregate_composition_and_rules']['rules'][0]
    first_rule['when'] = {'otype': 'T0'}
    definition = {**deepcopy(data['definitions'][0]), 'definition_version': 2, 'name_en': 'Version two'}
    definition['content_sha256'] = content_hash(definition)
    profile = {**deepcopy(data['output_profiles'][0]), 'version': 2, 'definition_version': 2}
    profile['content_sha256'] = content_hash(profile)
    second_rule = {**deepcopy(first_rule), 'rule_id': 'second', 'when': {'otype': 'T1'},
        'definition_ref': {'id': definition['property_id'], 'version': '2', 'content_sha256': definition['content_sha256']},
        'profile_ref': {'id': profile['profile_id'], 'version': 2, 'content_sha256': profile['content_sha256']}}
    data['definitions'].append(definition)
    data['output_profiles'].append(profile)
    data['unapproved_aggregate_composition_and_rules']['rules'].append(second_rule)
    data['build_only_symbolic_support'] = finite_support([first_rule, second_rule])
    prepared = CandidateRegistry(candidate)
    first = prepared.select_context(candidate, accepted_otypes=['T0'], subject_class_id='synthetic-subject')
    second = prepared.select_context(candidate, accepted_otypes=['T1'], subject_class_id='synthetic-subject')
    assert first['bindings'][0]['definition']['definition_version'] == 1
    assert second['bindings'][0]['definition']['definition_version'] == 2
    assert second['bindings'][0]['output_profile']['version'] == 2


def test_compilation_keeps_preoptimization_manifest_and_binding_hashes(tmp_path):
    """Literal fingerprints captured from the original compiler before edits."""
    result = compile_candidate(synthetic_candidate(tmp_path))
    assert result['manifest']['release_id'] == 'consumer-aaaaaaaaaaaaaaaa-48b76100a0e3'
    assert result['manifest']['content_sha256'] == '206e41da3c0945611b3425d858ca81dfe53474d9f02bcd0adf789c4b6cdba866'
    assert result['manifest']['consumer_view_hash'] == 'f24cf2b52d2d5bd04bcb378b4e83c791fb7589251c1c3f66f8da25bf097ef293'


@pytest.mark.parametrize('damage,code', [
    ('ast', 'CANDIDATE_SYMBOLIC_AST_MISMATCH'),
    ('node', 'CANDIDATE_BDD_STRUCTURE'),
    ('variable', 'CANDIDATE_BDD_VARIABLE'),
    ('outcome', 'CANDIDATE_OUTCOME_MISMATCH'),
    ('reference', 'CANDIDATE_BINDING_REFERENCE'),
])
def test_prepared_selection_retains_source_and_bdd_errors(tmp_path, damage, code):
    candidate = synthetic_candidate(tmp_path)
    table = candidate['data']['build_only_symbolic_support']['tables'][0]
    if damage == 'ast':
        candidate['data']['unapproved_aggregate_composition_and_rules']['rules'][0]['when'] = {'otype': 'absent'}
    elif damage == 'node':
        table['nodes'].clear()
    elif damage == 'variable':
        for node in table['nodes']:
            node['variable_index'] = -1
    elif damage == 'outcome':
        for partition in table['partitions']:
            partition['outcome'] = 'invalid'
    else:
        candidate['data']['definitions'][0]['content_sha256'] = 'f' * 64
    for reader in (CandidateRegistry(), CandidateRegistry(candidate)):
        with pytest.raises(DomainError) as caught:
            reader.select_context(candidate, accepted_otypes=['T0'], subject_class_id='synthetic-subject')
        assert caught.value.code == code


def test_prepared_selection_matches_every_context_and_exact_hash(tmp_path):
    candidate = synthetic_candidate(tmp_path)
    prepared = CandidateRegistry(candidate)
    for flags in product((False, True), repeat=2):
        types = [t for t, enabled in zip(['T0', 'T1'], flags) if enabled]
        expected = CandidateRegistry().select_context(candidate, accepted_otypes=types, subject_class_id='synthetic-subject')
        actual = prepared.select_context(candidate, accepted_otypes=types, subject_class_id='synthetic-subject')
        assert actual == expected
        assert digest(actual) == digest(expected)


@pytest.fixture
def installed_distribution(tmp_path, monkeypatch):
    import astroquery_ai.registry.distribution as distribution
    candidate = synthetic_candidate(tmp_path)
    manifest = compile_candidate(candidate)['manifest']
    package = tmp_path / 'installed'
    package.mkdir()
    archive = package / 'runtime-inputs.json.xz'
    archive.write_bytes(lzma.compress(canonical({'format': 'reviewed-runtime-inputs/1',
        'candidate': {**candidate, 'report': {**candidate['report'], 'manifest_file_sha256': 'a' * 64}},
        'science': {**candidate['science'], 'config_sha256': 'b' * 64}, 'amendment': None})))
    (package / 'manifest.json').write_bytes(canonical(manifest))
    resource = tmp_path / 'resource'
    production = resource / 'property_registry/production'
    production.mkdir(parents=True)
    pin = production / 'release.json'
    pin.write_bytes(canonical({'runtime_inputs_sha256': sha256(archive.read_bytes()).hexdigest(),
        'release_id': manifest['release_id'], 'manifest_content_sha256': manifest['content_sha256']}))
    monkeypatch.setattr(distribution, 'resource_root', lambda: resource)
    return RegistryService(tmp_path / 'registry', None), package, archive, pin


def test_same_service_concurrent_loads_compile_once(installed_distribution, monkeypatch):
    import astroquery_ai.registry.distribution as distribution
    service, package, _, _ = installed_distribution
    real = distribution.compile_verified_inputs
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(distribution, 'compile_verified_inputs', counted)
    gate = Barrier(8)
    def load(_):
        gate.wait(timeout=10)
        return service.validate(package)['manifest']
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(load, range(8)))
    assert all(value == results[0] for value in results)
    assert len(calls) == 1


def test_first_failed_distribution_compile_is_not_cached(installed_distribution, monkeypatch):
    import astroquery_ai.registry.distribution as distribution
    service, package, _, _ = installed_distribution
    real = distribution.compile_verified_inputs
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise DomainError('SYNTHETIC_TRANSIENT', 'Synthetic retry case', 422)
        return real(*args, **kwargs)
    monkeypatch.setattr(distribution, 'compile_verified_inputs', fail_once)
    with pytest.raises(DomainError) as caught:
        service.validate(package)
    assert caught.value.code == 'SYNTHETIC_TRANSIENT'
    assert str(package) not in service._consumer_cache
    assert service.validate(package)['manifest']['release_id'].startswith('consumer-')
    assert len(calls) == 2


def test_distribution_change_rejects_and_failure_retries(installed_distribution):
    service, package, archive, pin = installed_distribution
    original = archive.read_bytes()
    manifest = service.validate(package)['manifest']
    archive.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    for _ in range(2):
        with pytest.raises(DomainError) as caught:
            service.validate(package)
        assert caught.value.code == 'PRODUCT_LIBRARY_HASH'
    archive.write_bytes(original)
    assert service.validate(package)['manifest'] == manifest
    pin.write_bytes(b'{}')
    with pytest.raises(DomainError):
        service.validate(package)
