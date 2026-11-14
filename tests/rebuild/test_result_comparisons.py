"""Synthetic basic juxtaposition; strict science verdicts stay separate."""
from copy import deepcopy

from astroquery_ai.science.differences import compare
from tests.rebuild.factories import measurement, derived, ref, error_component


def inputs():
    records = [measurement('first', value='8.1', components=[error_component()]), measurement('second', value='8.2')]
    profile = {'profile_id': 'synthetic-profile', 'version': 1, 'content_sha256': ref()['content_sha256']}
    binding = {'property_id': 'synthetic-property', 'definition': {'measurement_conditions_schema': [
        {'key': 'method', 'required_for_comparison': True, 'required_for_identity': False}]}, 'output_profile': profile}
    outputs = []
    for record in records:
        output = derived(record)
        output.update(source_representation_hash=record['content_sha256'],
            output_profile_ref={'id': profile['profile_id'], 'version': profile['version'], 'content_sha256': profile['content_sha256']},
            coordinate_units={'source': 'm', 'target': 'm'})
        outputs.append(output)
    return records, outputs, binding


def test_correct_values_appear_without_strict_prerequisites_or_explanation_calls():
    records, outputs, binding = inputs()
    before = deepcopy(records)
    report = compare(records, outputs, [], [binding], ref('snapshot'))
    assert not report['groups'] and len(report['limitations']) == 2
    basic = report['result_comparisons']
    assert basic['measurement_count'] == 2 and len(basic['groups']) == 1
    group = basic['groups'][0]
    assert group['coordinate_groups'][0]['value_relation'] == 'different_reported_numbers'
    assert group['coordinate_groups'][0]['strict_comparability_asserted'] is False
    assert group['rows'][0]['uncertainty'] == records[0]['uncertainty']
    assert records == before and basic['model_calls'] == basic['additional_source_reads'] == 0


def test_native_only_or_stale_processed_value_remains_visible_without_math():
    records, outputs, binding = inputs()
    outputs[0].update(main_state='not_run', value_typed=None)
    outputs[1]['source_representation_hash'] = 'not-the-source-version'
    basic = compare(records, outputs, [], [binding], ref())['result_comparisons']
    assert len(basic['groups'][0]['rows']) == 2
    assert not basic['groups'][0]['coordinate_groups']
    assert all(row['numeric_relation_state'] == 'not_evaluated' for row in basic['groups'][0]['rows'])


def test_different_target_definition_or_defining_band_stays_separate():
    records, outputs, binding = inputs()
    binding['definition']['measurement_conditions_schema'].append(
        {'key': 'synthetic-band', 'required_for_identity': True, 'required_for_comparison': True})
    contexts = [{'measurement_ref': {'id': r['measurement_id']}, 'conditions': [
        {'key': 'synthetic-band', 'state': 'known', 'value': band}]} for r, band in zip(records, ['A', 'B'])]
    basic = compare(records, outputs, contexts, [binding], ref())['result_comparisons']
    assert len(basic['groups']) == 2
    assert all(g['coordinate_groups'][0]['value_relation'] == 'single_value' for g in basic['groups'])
    records[1]['target_ref'] = ref('different-target')
    assert len(compare(records, outputs, [], [binding], ref())['result_comparisons']['groups']) == 2


def test_limits_and_incompatible_output_coordinates_do_not_become_points():
    records, outputs, binding = inputs()
    records[0]['limit'] = outputs[0]['limit'] = 'upper'
    outputs[1]['output_profile_ref'] = ref('unverified-alternative-profile')
    result = compare(records, outputs, [], [binding], ref())['result_comparisons']
    assert result['measurement_count'] == 2 and not result['groups'][0]['coordinate_groups']


def test_export_subset_does_not_repeat_full_group_difference_or_mutate_snapshot():
    from astroquery_ai.science.differences import select_result_comparisons
    records, outputs, binding = inputs()
    report = compare(records, outputs, [], [binding], ref())['result_comparisons']
    before = deepcopy(report)
    selected = select_result_comparisons(report, {'first'})
    assert selected['measurement_count'] == 1
    assert selected['groups'][0]['coordinate_groups'][0]['value_relation'] == 'single_value'
    assert selected['groups'][0]['measurement_ids'] == ['first']
    assert selected['groups'][0]['scope'] == 'export_selection'
    assert report == before
