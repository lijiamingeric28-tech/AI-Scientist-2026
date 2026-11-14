from copy import deepcopy

import pytest

from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.delivery import current_derived_representations
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.normalization_prompt import normalization_prompt
from tests.rebuild.factories import measurement, derived, ref, error_component


def representations():
    source = measurement(components=[error_component()])
    profile = ref('SYNTHETIC current output')
    binding = {'property_id': source['property_ref']['id'], 'output_profile': {
        'profile_id': profile['id'], 'version': profile['version'], 'content_sha256': profile['content_sha256']}}
    old, new = derived(source, 'not_run', 'not_run'), derived(source)
    for name, item in [('z-older', old), ('a-current', new)]:
        item.update(derived_id=name, source_representation_hash=source['content_sha256'], output_profile_ref=profile)
    selection = {'measurement_id': source['measurement_id'], 'source_hash': source['content_sha256'],
        'output_profile_ref': profile, 'derived_ref': {'id': new['derived_id'], 'version': 1, 'content_sha256': content_hash(new)}}
    return source, binding, old, new, selection


def test_current_representation_ignores_incidental_sort_order_and_retains_source():
    source, binding, old, new, selection = representations()
    before = deepcopy(source)
    assert current_derived_representations([source], [binding], [new, old], [selection]) == [new]
    assert current_derived_representations([source], [binding], [old, new], [selection]) == [new]
    assert source == before and old['status'] == 'not_run'


def test_legacy_unique_result_can_load_but_ambiguous_history_cannot_choose_a_best_value():
    source, binding, old, new, _ = representations()
    assert current_derived_representations([source], [binding], [new], []) == [new]
    with pytest.raises(DomainError) as failure:
        current_derived_representations([source], [binding], [new, old], [])
    assert failure.value.code == 'DERIVED_CURRENT_UNRESOLVED'
    new['output_profile_ref'] = ref('SYNTHETIC superseded profile')
    assert current_derived_representations([source], [binding], [new], []) == []


def test_new_source_revision_cannot_inherit_an_old_result_or_ignore_a_corrupt_current_pointer():
    source, binding, old, new, selection = representations()
    bad = deepcopy(selection)
    bad['derived_ref']['content_sha256'] = ref('SYNTHETIC corrupt')['content_sha256']
    with pytest.raises(DomainError) as failure:
        current_derived_representations([source], [binding], [new], [bad])
    assert failure.value.code == 'DERIVED_REFERENCE_MISMATCH'
    source['revision'] += 1
    source['content_sha256'] = content_hash(source)
    assert current_derived_representations([source], [binding], [old, new], [selection]) == []


def test_model_standardization_input_preserves_separate_errors_and_their_actual_units_and_bases():
    source = measurement(components=[error_component(), error_component('SYNTHETIC sys', role='sys')])
    source['uncertainty']['components'][1]['values'] = {'delta': '0.4'}
    source['uncertainty']['components'][1]['basis_ref'] = ref('SYNTHETIC actual basis')
    before = deepcopy(source)
    prompt = normalization_prompt(source, {'kind': 'linear'}, {'unit': 'cm'}, {},
        source_quote='SYNTHETIC quoted source', context={'conditions': []}, statements=[],
        basis_values={'SYNTHETIC actual basis': '2', 'unrelated basis': '99'},
        component_units={'source-unit': 'm', 'unrelated unit': 'kg'})
    assert prompt['source']['uncertainty']['components'] == before['uncertainty']['components']
    assert prompt['basis_values'] == {'SYNTHETIC actual basis': '2'}
    assert prompt['component_units'] == {'source-unit': 'm'}
    assert source == before
