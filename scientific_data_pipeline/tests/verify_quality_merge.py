"""
verify_quality_merge.py — Comprehensive verification of quality subgraph merge.
"""
import sys
sys.path.insert(0, '.')

def main():
    print('=' * 70)
    print('COMPREHENSIVE MERGE VERIFICATION')
    print('=' * 70)

    errors = []

    # ── 1. Import verifications ──
    print()
    print('1. Import Verification')
    print('-' * 40)
    try:
        from subgraphs.quality.configs import (
            load_yaml, set_research_domain, get_research_domain,
            load_domain_config, load_domain_schema_config,
        )
        print('   [PASS] configs/__init__.py (all functions present)')
    except Exception as e:
        errors.append(f'configs import: {e}')
        print(f'   [FAIL] configs: {e}')

    try:
        from subgraphs.quality.state import QualityGraphState, make_initial_state
        print('   [PASS] state.py')
    except Exception as e:
        errors.append(f'state import: {e}')
        print(f'   [FAIL] state: {e}')

    try:
        from subgraphs.quality.routers import (
            loop_controller_node, check_retry,
            NODE_ASSESSMENT, NODE_NORMALIZATION, NODE_CONFLICT,
            NODE_EXPORT, NODE_HUMAN_REVIEW, NODE_LOOP,
            ASSESSMENT_ROUTE_MAP, NORMALIZATION_ROUTE_MAP, CONFLICT_ROUTE_MAP,
            HUMAN_REVIEW_ROUTE_MAP,
        )
        assert 'Conflict' in NORMALIZATION_ROUTE_MAP, 'Missing Conflict in NORMALIZATION_ROUTE_MAP'
        print('   [PASS] routers.py (NORMALIZATION_ROUTE_MAP includes Conflict)')
    except Exception as e:
        errors.append(f'routers import: {e}')
        print(f'   [FAIL] routers: {e}')

    try:
        from subgraphs.quality.graph import (
            build_quality_graph, compile_quality_graph,
            route_after_assessment, route_after_dispatch,
            route_after_normalization, route_after_conflict,
            route_after_human_review,
        )
        print('   [PASS] graph.py')
    except Exception as e:
        errors.append(f'graph import: {e}')
        print(f'   [FAIL] graph: {e}')

    try:
        from main_graph.wrappers import create_quality_wrapper
        print('   [PASS] wrappers.py (single create_quality_wrapper)')
    except Exception as e:
        errors.append(f'wrappers import: {e}')
        print(f'   [FAIL] wrappers: {e}')

    # ── 2. Graph compilation ──
    print()
    print('2. Graph Compilation')
    print('-' * 40)
    try:
        graph = compile_quality_graph()
        nodes = list(graph.nodes.keys()) if hasattr(graph, 'nodes') else list(graph.builder._nodes.keys())
        expected = ['__start__', 'assessment_graph', 'normalization_graph', 'conflict_graph',
                    'export_graph', 'loop_controller', 'human_review', 'dispatch', 'pre_normalization']
        missing = [n for n in expected if n not in nodes]
        if missing:
            errors.append(f'Missing graph nodes: {missing}')
            print(f'   [FAIL] Missing nodes: {missing}')
        else:
            print(f'   [PASS] All {len(expected)} nodes present')
    except Exception as e:
        errors.append(f'graph compilation: {e}')
        print(f'   [FAIL] Compilation: {e}')

    # ── 3. Routing Logic Tests ──
    print()
    print('3. Routing Logic Verification')
    print('-' * 40)

    # Test A->B->C path (newly fixed)
    state = {
        'workflow_state': {'_from_conflict': False, '_loop_count': 0},
        'report_state': {'normalization': {'validation': {'needs_conflict_analysis': True}}},
    }
    result = route_after_normalization(state)
    if result == NODE_CONFLICT:
        print('   [PASS] A->B->C: Normalization detects conflicts -> Conflict')
    else:
        errors.append(f'A->B->C routing: expected {NODE_CONFLICT}, got {result}')
        print(f'   [FAIL] A->B->C: expected {NODE_CONFLICT}, got {result}')

    # Test A->B->D path
    state = {
        'workflow_state': {'_from_conflict': False, '_loop_count': 0},
        'report_state': {'normalization': {'validation': {'needs_conflict_analysis': False}}},
    }
    result = route_after_normalization(state)
    if result == NODE_EXPORT:
        print('   [PASS] A->B->D: Normalization clean -> Export')
    else:
        errors.append(f'A->B->D routing: expected {NODE_EXPORT}, got {result}')
        print(f'   [FAIL] A->B->D: expected {NODE_EXPORT}, got {result}')

    # Test C->B->C path
    state = {
        'workflow_state': {'_from_conflict': True, '_loop_count': 1},
        'report_state': {'normalization': {}},
    }
    result = route_after_normalization(state)
    if result == NODE_CONFLICT:
        print('   [PASS] C->B->C: from conflict -> back to Conflict')
    else:
        errors.append(f'C->B->C routing: expected {NODE_CONFLICT}, got {result}')
        print(f'   [FAIL] C->B->C: expected {NODE_CONFLICT}, got {result}')

    # Test C->B routing (was returning "pre_normalization")
    state = {
        'workflow_state': {'_loop_count': 0, 'route_decision': ''},
        'report_state': {'conflict': {'resolution_report': {'route_decision': 'Normalization'}}},
    }
    result = route_after_conflict(state)
    if result == NODE_NORMALIZATION:
        print('   [PASS] C->B: Conflict needs Normalization -> returns NODE_NORMALIZATION')
    else:
        errors.append(f'C->B routing: expected {NODE_NORMALIZATION}, got {result}')
        print(f'   [FAIL] C->B: expected {NODE_NORMALIZATION}, got {result}')

    # Test C->D path
    state = {
        'workflow_state': {'_loop_count': 0, 'route_decision': ''},
        'report_state': {'conflict': {'resolution_report': {'route_decision': 'Export'}}},
    }
    result = route_after_conflict(state)
    if result == NODE_EXPORT:
        print('   [PASS] C->D: Conflict resolved -> Export')
    else:
        errors.append(f'C->D routing: expected {NODE_EXPORT}, got {result}')
        print(f'   [FAIL] C->D: expected {NODE_EXPORT}, got {result}')

    # Test C->E path
    state = {
        'workflow_state': {'_loop_count': 0, 'route_decision': ''},
        'report_state': {'conflict': {'resolution_report': {'route_decision': 'HumanReview'}}},
    }
    result = route_after_conflict(state)
    if result == NODE_HUMAN_REVIEW:
        print('   [PASS] C->E: Cannot resolve -> HumanReview')
    else:
        errors.append(f'C->E routing: expected {NODE_HUMAN_REVIEW}, got {result}')
        print(f'   [FAIL] C->E: expected {NODE_HUMAN_REVIEW}, got {result}')

    # Test max loops guard
    state = {
        'workflow_state': {'_loop_count': 3, 'route_decision': ''},
        'report_state': {'conflict': {'resolution_report': {'route_decision': 'Normalization'}}},
    }
    result = route_after_conflict(state)
    if result == NODE_EXPORT:
        print('   [PASS] Max loops: force Export after 3 cycles')
    else:
        errors.append(f'Max loops: expected {NODE_EXPORT}, got {result}')
        print(f'   [FAIL] Max loops: expected {NODE_EXPORT}, got {result}')

    # ── 4. Tool Import Verification ──
    print()
    print('4. Tool Import Verification')
    print('-' * 40)

    tool_checks = {
        'assessment': [
            ('completeness', 'check_completeness'),
            ('consistency', 'check_consistency'),
            ('format_checker', 'check_format'),
            ('source_checker', 'check_source_reliability'),
            ('statistical_conflict', 'detect_conflicts_statistical'),
            ('adaptive_threshold', 'AdaptiveThresholdEngine'),
            ('quality_scoring', 'compute_quality_score'),
            ('distribution', 'profile_field_distributions'),
            ('outlier', 'detect_all_fields'),
            ('semantic_type', 'infer_all_fields'),
            ('extraction_quality', 'check_extraction_quality'),
        ],
        'normalization': [
            ('schema_mapping', 'map_to_target_schema'),
            ('field_standardizer', 'standardize_field_values'),
            ('unit_converter', 'convert_units'),
            ('missing_value_handler', 'handle_missing_values'),
            ('duplicate_handler', 'handle_duplicates'),
            ('format_standardizer', 'standardize_format'),
        ],
        'conflict': [
            ('conflict_extractor', 'extract_conflicts'),
            ('context_builder', 'build_conflict_context'),
            ('rule_classifier', 'classify_conflict_rule'),
            ('source_reliability_analyzer', 'analyze_source_reliability'),
            ('domain_rule_engine', 'match_domain_rules'),
            ('statistical_evidence', 'analyze_statistical_evidence'),
            ('contextual_evidence', 'collect_contextual_evidence'),
            ('confidence_evaluator', 'evaluate_confidence'),
        ],
        'export': [
            ('data_organizer', 'organize_data'),
            ('format_exporter', 'export_formats'),
            ('schema_formatter', 'format_to_schema'),
            ('metadata_generator', 'generate_metadata'),
            ('traceability_builder', 'build_traceability'),
            ('output_validator', 'validate_output'),
        ],
    }

    tool_count = 0
    tool_errors = 0
    for category, tools in tool_checks.items():
        for module_name, func_name in tools:
            tool_count += 1
            try:
                mod = __import__(
                    f'subgraphs.quality.tools.{category}.{module_name}',
                    fromlist=[func_name]
                )
                getattr(mod, func_name)
            except Exception as e:
                tool_errors += 1
                errors.append(f'{category}/{module_name}.{func_name}: {e}')
                print(f'   [FAIL] {category}/{module_name}.{func_name}: {e}')

    if tool_errors == 0:
        print(f'   [PASS] All {tool_count} tools importable')

    # ── 5. End-to-end with data ──
    print()
    print('5. End-to-End Pipeline Test')
    print('-' * 40)

    try:
        from subgraphs.quality.graph import compile_quality_graph
        graph = compile_quality_graph()

        test_data = {
            'sources': [{
                'source_id': 'src-test',
                'source_type': 'paper',
                'doi': '10.1234/test.2025',
                'title': 'Test: Clean Data',
                'authors': ['Author X'],
                'year': 2025,
                'journal': 'Nature Materials',
                'access_path': '/test',
                'retrieval_priority': 0.95,
            }],
            'records': [{
                'record_id': 'rec-test-1',
                'source_id': 'src-test',
                'field_name': 'yield_strength',
                'field_value': 500.0,
                'field_unit': 'MPa',
                'trace_id': 't1',
                'provenance': {'page': 1, 'bbox': [10, 20, 30, 40]},
                'extraction_method': 'llm_table',
            }],
        }

        quality_input = {
            'context_state': {
                'clarified_intent': {'entities': ['material'], 'properties': ['yield_strength'], 'conditions': {}},
                'research_domain': 'materials_science',
                'target_schema': {'fields': [{'name': 'yield_strength', 'standard_unit': 'MPa'}]},
            },
            'data_state': {'input_data': test_data, 'current_data': test_data, 'data_trace': []},
            'report_state': {},
            'workflow_state': {
                'current_node': 'start', 'execution_status': 'Success',
                'iteration_counter': 0, 'retry_counter': 0,
                'route_decision': '', 'workflow_history': [],
            },
            'output_state': {},
        }

        result = graph.invoke(quality_input)
        rs = result.get('report_state', {})
        os_ = result.get('output_state', {})

        quality = rs.get('quality', {})
        per_source_routes = quality.get('per_source_routes', {})
        route_counts = quality.get('route_counts', {})

        print(f'   Route distribution: {route_counts}')
        print(f'   Per-source routes: {per_source_routes}')

        output_sd = os_.get('structured_data', {})
        print(f'   Output rows: {output_sd.get("row_count", 0)}, cols: {output_sd.get("column_count", 0)}')

        print('   [PASS] End-to-end pipeline completes successfully')
    except Exception as e:
        errors.append(f'E2E test: {e}')
        print(f'   [FAIL] E2E: {e}')
        import traceback
        traceback.print_exc()

    # ── 6. Data integrity check ──
    print()
    print('6. Data Integrity')
    print('-' * 40)
    input_count = 1  # from test_data
    output_count = os_.get('structured_data', {}).get('row_count', 0)
    if output_count == input_count:
        print(f'   [PASS] Input={input_count}, Output={output_count} (no data loss)')
    else:
        errors.append(f'Data loss: input={input_count}, output={output_count}')
        print(f'   [FAIL] Input={input_count}, Output={output_count}')

    # ── Summary ──
    print()
    print('=' * 70)
    if errors:
        print(f'VERIFICATION FAILED: {len(errors)} error(s)')
        for e in errors:
            print(f'  - {e}')
    else:
        print('ALL VERIFICATIONS PASSED!')
    print('=' * 70)

    return len(errors) == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
