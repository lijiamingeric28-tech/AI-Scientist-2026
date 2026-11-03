"""Regressions for read-only delivery projections, with deliberately small fixtures."""
import copy
import json
import sqlite3

from astroquery_ai.application.research_views import activities, historical_insights, enrich_materials, coverage_matrix


def body():
    return {'delivery_id': 'd', 'revision': 1, 'snapshot_ref': {'id': 's', 'version': 1},
            'definitions': [], 'measurements': [], 'derived': [], 'provenance_bundle': {}}


def measurement(mid):
    return {'measurement_id': mid, 'property_ref': {'id': 'p'}, 'source_ref': {'id': 'paper'},
            'interpretation_ref': {'id': 'i'}, 'value': {'kind': 'real', 'value': '0'},
            'raw_value': '0', 'unit': 'K'}


def test_lineage_keeps_siblings_separate_and_includes_shared_parent():
    doc = body()
    doc['measurements'] = [measurement('ma'), measurement('mb')]
    doc['provenance_bundle'] = {
        'candidate': [{'candidate_id': cid, 'proposal': {'raw_value': cid, 'property_id': 'p'}}
                      for cid in ['root', 'a', 'b']],
        'quality_candidate_link': [
            {'candidate_ref': {'id': 'root'}, 'parent_ref': None},
            {'candidate_ref': {'id': 'a'}, 'parent_ref': {'id': 'root'}},
            {'candidate_ref': {'id': 'b'}, 'parent_ref': {'id': 'root'}}],
        'quality_decision': [
            {'root_id': 'root', 'candidate_ref': {'id': 'root'}, 'state': 'reextraction_requested'},
            {'root_id': 'root', 'candidate_ref': {'id': 'a'}, 'measurement_ref': {'id': 'ma'}, 'state': 'supported'},
            {'root_id': 'root', 'candidate_ref': {'id': 'b'}, 'measurement_ref': {'id': 'mb'}, 'state': 'supported'}],
        'quality_reextraction_action': [{'root_id': 'root', 'parent_candidate_ref': {'id': 'root'}, 'source_id': 'paper', 'property_id': 'p'}],
        'quality_reextraction_result': [{'root_id': 'root', 'parent_ref': {'id': 'root'}, 'candidate_count': 2, 'complete': True}],
    }
    before = copy.deepcopy(doc)
    rows = [r for r in activities(doc) if 'ma' in r['measurement_ids']]
    assert 'check-root' in [r['id'] for r in rows]
    assert 'check-a' in [r['id'] for r in rows]
    assert 'check-b' not in [r['id'] for r in rows]
    kinds = [r['kind'] for r in rows]
    assert kinds[:5] == ['original', 'quality', 'reextraction', 'original', 'quality']
    assert doc == before


def test_failed_normalization_does_not_replace_zero_or_claim_conversion():
    doc = body()
    doc['measurements'] = [measurement('m')]
    doc['derived'] = [{'measurement_id': 'm', 'main_state': 'not_run', 'uncertainty_typed': None}]
    doc['provenance_bundle']['processing_receipts'] = [{'input_ref': {'id': 'm'}, 'status': 'failed', 'postcheck': 'failed'}]
    row = next(r for r in activities(doc) if r['kind'] == 'representation')
    assert row['status'] == 'failed' and not row['actual_change']
    assert row['before']['raw'] == '0' and row['after'] is None
    assert doc['measurements'][0]['value']['value'] == '0'


def test_no_change_is_a_receipted_operation_without_change_event():
    doc = body()
    doc['measurements'] = [measurement('m')]
    doc['derived'] = [{'measurement_id': 'm', 'main_state': 'ready', 'scientific_operation': {'operation': 'same_value_target'},
                       'value_typed': {'kind': 'real', 'value': '0'}, 'uncertainty_typed': {'components': []}}]
    row = next(r for r in activities(doc) if r['kind'] == 'representation')
    assert row['status'] == 'no_change' and not row['actual_change']


def test_reextraction_without_measurement_still_has_an_activity():
    doc = body()
    doc['provenance_bundle']['quality_reextraction_action'] = [{'root_id': 'r', 'parent_candidate_ref': {'id': 'r'}, 'source_id': 'paper', 'property_id': 'p'}]
    doc['provenance_bundle']['quality_reextraction_result'] = [{'parent_ref': {'id': 'r'}, 'outcome': 'no_target_candidate', 'candidate_count': 0}]
    rows = activities(doc)
    assert len(rows) == 1 and rows[0]['status'] == 'no_target_candidate'
    assert rows[0]['measurement_ids'] == []


def test_historical_fallback_keeps_early_insight_even_on_same_snapshot():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE objects(task_id,kind,object_id,version,created_at,payload)')
    doc = body()
    for version, at, state in [(1, '10', 'pending'), (2, '20', 'complete')]:
        report = {'delivery_id': 'd', 'snapshot_ref': doc['snapshot_ref'], 'status': state}
        conn.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)', ('t', 'insight', 'i', version, at, json.dumps(report)))
    assert historical_insights(conn, 't', doc, '15')[0]['status'] == 'pending'
    assert historical_insights(conn, 't', doc, '25')[0]['status'] == 'complete'
    assert historical_insights(conn, 't', doc, None) == []


def test_paper_can_be_read_without_contributing_a_measurement():
    doc = body()
    doc['definitions'] = [{'property_id': 'p', 'definition': {'name_cn': '测试性质'}}]
    doc['provenance_bundle']['completion_scope'] = [{'materials': [{'material_id': 'paper:w', 'ranges': [{'property_id': 'p', 'page': 1}]}]}]
    rows = [{'material_id': 'w', 'source_id': 'w', 'kind': 'paper', 'work': {'work_id': 'w'}}]
    facts = {'preparation': {'pools': {'p': {'evaluated': ['w'], 'acquired': ['w'], 'decisions': {'w': {'decision': 'relevant'}}}}},
             'reading': [{'work_id': 'w', 'property_ids': ['p'], 'core_pages': [1], 'coverage': 'checked'}]}
    row = enrich_materials(rows, doc, facts, {})[0]['assignments'][0]
    assert row['allocated'] and row['eligible'] and row['read_pages'] == [1]
    assert row['candidate_count'] == 0 and row['measurement_ids'] == []


def test_failed_reading_and_unchecked_reading_remain_distinct():
    doc = body()
    doc['definitions'] = [{'property_id': 'p', 'definition': {'name_cn': '测试性质'}}]
    failed = {'reading': [{'work_id': 'w', 'property_ids': ['p'], 'core_pages': [1], 'coverage': 'technical_failure'}]}
    assert coverage_matrix(doc, {}, {}, None, failed)[0]['cells']['extraction']['state'] == 'technical_failure'
    assert coverage_matrix(doc, {}, {}, None, {})[0]['cells']['extraction']['state'] == 'not_checked'
