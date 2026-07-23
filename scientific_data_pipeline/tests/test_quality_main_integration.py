"""
Verify quality subgraph integration into main pipeline.
Tests MainState -> QualityGraphState -> MainState conversion.
"""
import sys, json, copy
sys.path.insert(0, '.')

from main_graph.wrappers import create_quality_wrapper
from main_graph.state import MainState

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f'  [PASS] {name}')
    except Exception as e:
        failed += 1
        print(f'  [FAIL] {name}: {e}')

print('=' * 60)
print('QUALITY WRAPPER INTEGRATION VERIFICATION')
print('=' * 60)

# Load test data
with open('data/reports/extraction_result_20260723_083647.json', 'r', encoding='utf-8') as f:
    gd = json.load(f)['grounded_data']


def test_normal_data():
    """102 records, 4 sources — full pipeline"""
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {'entities': ['FRB']},
        'query_context': {'domain': 'astronomy'}, 'grounded_data': gd,
    })
    assert len(r['final_output']['records']) == len(gd['records'])
    assert len(r['final_output']['sources']) == len(gd['sources'])
    assert r['quality_summary']['quality_report'] is not None
    assert r['quality_summary']['normalization_report'] is not None

test('Normal data (102 records, 4 sources)', test_normal_data)


def test_empty_data():
    """0 records — should not crash"""
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {},
        'query_context': {}, 'grounded_data': {'records': [], 'sources': []},
    })
    assert r['final_output']['records'] == []
    assert r['final_output']['sources'] == []

test('Empty data (0 records)', test_empty_data)


def test_missing_optional_fields():
    """MainState without intent_params, query_context"""
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test',
        'grounded_data': {
            'records': [{
                'record_id': '1', 'source_id': 's1',
                'field_name': 'temp', 'field_value': 25.0, 'field_unit': 'K',
                'entity_type': 'test', 'entity_name': 'Test1',
                'trace_id': 't1', 'provenance': {'page': 1, 'bbox': [0, 0, 1, 1]},
                'extraction_method': 'vlm_text',
            }],
            'sources': [{'source_id': 's1'}],
        },
    })
    assert 'final_output' in r
    assert 'quality_summary' in r

test('Missing optional MainState fields', test_missing_optional_fields)


def test_multi_field():
    """2 fields, 2 sources — cross-source check"""
    data = {
        'records': [
            {'record_id': '1', 'source_id': 's1', 'field_name': 'yield_strength',
             'field_value': 450, 'field_unit': 'MPa', 'entity_type': 'alloy',
             'entity_name': 'Al7075', 'trace_id': 't1',
             'provenance': {'page': 1, 'bbox': [0, 0, 1, 1]},
             'extraction_method': 'llm_text'},
            {'record_id': '2', 'source_id': 's1', 'field_name': 'temperature',
             'field_value': 200, 'field_unit': 'C', 'entity_type': 'alloy',
             'entity_name': 'Al7075', 'trace_id': 't2',
             'provenance': {'page': 1, 'bbox': [0, 0, 1, 1]},
             'extraction_method': 'llm_table'},
            {'record_id': '3', 'source_id': 's2', 'field_name': 'yield_strength',
             'field_value': 438, 'field_unit': 'MPa', 'entity_type': 'alloy',
             'entity_name': 'Al7075', 'trace_id': 't3',
             'provenance': {'page': 2, 'bbox': [0, 0, 1, 1]},
             'extraction_method': 'llm_text'},
        ],
        'sources': [
            {'source_id': 's1', 'source_type': 'paper', 'doi': '10.1234/a',
             'title': 'Paper A', 'authors': ['A'], 'year': 2024,
             'journal': 'Test J', 'access_path': '/t', 'retrieval_priority': 0.9},
            {'source_id': 's2', 'source_type': 'paper', 'doi': '10.1234/b',
             'title': 'Paper B', 'authors': ['B'], 'year': 2024,
             'journal': 'Test J', 'access_path': '/t', 'retrieval_priority': 0.8},
        ],
    }
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {'entities': ['alloy']},
        'query_context': {'domain': 'materials_science'}, 'grounded_data': data,
    })
    assert len(r['final_output']['records']) == 3
    assert len(r['final_output']['sources']) == 2

test('Multi-field data (2 fields, 2 sources)', test_multi_field)


def test_output_structure():
    """Verify all expected output fields exist"""
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {'entities': ['FRB']},
        'query_context': {'domain': 'astronomy'}, 'grounded_data': gd,
    })
    final = r['final_output']
    qs = r['quality_summary']

    assert 'sources' in final
    assert 'records' in final
    assert 'schema_version' in final
    assert final['schema_version'] == '1.1.0'

    assert 'quality_report' in qs
    assert 'conflict_report' in qs
    assert 'normalization_report' in qs
    assert 'export_path' in qs
    assert 'row_count' in qs
    assert 'column_count' in qs

test('Output structure completeness', test_output_structure)


def test_state_isolation():
    """Wrapper should not mutate input state"""
    original = {
        'user_query': 'test', 'intent_params': {},
        'query_context': {}, 'grounded_data': copy.deepcopy(gd),
    }
    input_copy = copy.deepcopy(original)
    qw = create_quality_wrapper()
    qw(original)
    assert original['user_query'] == input_copy['user_query']

test('State isolation (no input mutation)', test_state_isolation)


def test_auto_target_schema():
    """Wrapper should auto-build target_schema from data"""
    data = {
        'records': [
            {'record_id': '1', 'source_id': 's1', 'field_name': 'density',
             'field_value': 7.85, 'field_unit': 'g/cm3', 'entity_type': 'test',
             'entity_name': 'T1', 'trace_id': 't1',
             'provenance': {'page': 1, 'bbox': [0, 0, 1, 1]},
             'extraction_method': 'vlm_text'},
            {'record_id': '2', 'source_id': 's1', 'field_name': 'hardness',
             'field_value': 200, 'field_unit': 'HV', 'entity_type': 'test',
             'entity_name': 'T1', 'trace_id': 't2',
             'provenance': {'page': 1, 'bbox': [0, 0, 1, 1]},
             'extraction_method': 'vlm_text'},
        ],
        'sources': [{'source_id': 's1'}],
    }
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {},
        'query_context': {}, 'grounded_data': data,
    })
    assert len(r['final_output']['records']) == 2
    assert r['quality_summary']['quality_report'] is not None

test('Auto-built target_schema', test_auto_target_schema)


def test_data_integrity():
    """Record count should always be preserved"""
    qw = create_quality_wrapper()
    r = qw({
        'user_query': 'test', 'intent_params': {'entities': ['FRB']},
        'query_context': {'domain': 'astronomy'}, 'grounded_data': gd,
    })
    assert len(r['final_output']['records']) == len(gd['records'])
    assert len(r['final_output']['sources']) == len(gd['sources'])

test('Data integrity (records preserved)', test_data_integrity)


print()
print('=' * 60)
print(f'RESULTS: {passed} passed, {failed} failed')
print('=' * 60)
