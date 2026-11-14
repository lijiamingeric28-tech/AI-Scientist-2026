from copy import deepcopy
import asyncio
import httpx

import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.catalog_context import (
    MAX_HEADER_BYTES, visible_columns, planned_partitions, quarantine_unseen, required_fields,
    retain_declared_errors,
)
from astroquery_ai.science.catalog_document import parse_readme, document_view, readme_url, select_cached_document
from astroquery_ai.science.workflow.catalog_service import CatalogService
from astroquery_ai.science.catalog_header import interpret_header


def test_remote_field_requires_full_metadata_and_does_not_erase_valid_sibling():
    columns = [{'name': f'SYNTHETIC_{i}', 'description': 'Complete synthetic description ' * 12,
                'datatype': 'double', 'unit_text': 'm', 'ucd': ''} for i in range(150)]
    columns[0].update(name='Name', ucd='meta.id;meta.main', datatype='char')
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': columns}
    spec = {'target': {'target_id': 'SYNTHETIC', 'main_id': 'SYNTHETIC_AQ'}, 'properties': []}
    targets = ['SYNTHETIC_1', 'SYNTHETIC_2']
    initial = CatalogService.header_prompt(table, spec, targets)
    assert len(canonical(initial)) <= MAX_HEADER_BYTES
    assert visible_columns(initial) == {'Name', *targets}
    assert len(initial['column_index']) == 150
    def mapping(column, errors):
        return {'property_id': 'SYNTHETIC-length', 'value_column': column,
            'error_columns': errors, 'source_unit': 'm', 'source_representation': 'linear'}
    plan = {'id_column': 'Name', 'properties': [mapping('SYNTHETIC_1', ['SYNTHETIC_140']), mapping('SYNTHETIC_2', [])]}
    kept, gaps = quarantine_unseen(plan, visible_columns(initial))
    assert len(kept['properties']) == 1 and gaps[0]['columns'] == ['SYNTHETIC_140']
    completed = CatalogService.header_prompt(table, spec, targets, required=required_fields(plan))
    assert 'SYNTHETIC_140' in visible_columns(completed)
    assert len(quarantine_unseen(plan, visible_columns(completed))[0]['properties']) == 2


def test_pre_dispatch_partition_keeps_whole_descriptions_and_lists_unfit_work():
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': [
        {'name': f'field_{i}', 'description': 'SYNTHETIC Complete local definition. ' * (2000 if i == 5 else 90)}
        for i in range(12)]}
    spec = {'target': {'main_id': 'SYNTHETIC_AQ'}, 'properties': []}
    partitions, gaps = planned_partitions(table, spec, CatalogService.header_prompt)
    assert {n for p in partitions for n in p['target_columns']} == {f'field_{i}' for i in range(12) if i != 5}
    assert gaps == [{'target_columns': ['field_5'], 'property_ids': [],
                     'reason': 'single_complete_field_definition_exceeds_input_bound', 'paid_calls': 0}]
    for p in partitions:
        prompt = CatalogService.header_prompt(table, spec, p['target_columns'])
        for column in prompt['table']['columns']:
            name = column[prompt['table']['column_attributes'].index('name')]
            description = column[prompt['table']['column_attributes'].index('description')]
            assert description == next(c['description'] for c in table['columns'] if c['name'] == name)


def test_document_closure_keeps_cycles_notes_and_overlapping_literal_labels():
    doc = {'parsed': {'fields': {'A': [{'text': 'A uses A-B (1)'}],
                                 'A-B': [{'text': 'A-B uses C (2)'}],
                                 'C': [{'text': 'C uses A'}]},
                      'notes': {'1': [{'text': 'Note (1): see C (2)'}],
                                '2': [{'text': 'Note (2): see A (1)'}]}}}
    before = deepcopy(doc)
    first = document_view(doc, {'A'}, ['A', 'A-B', 'C'])
    assert set(first['field_descriptions']) == {'A', 'A-B', 'C'}
    assert set(first['notes']) == {'1', '2'}
    assert set(first['referenced_column_names']) == {'A', 'A-B', 'C'}
    assert document_view(doc, {'A-B'}, ['A', 'A-B', 'C']) == first
    assert doc == before


def test_explicit_definition_dependencies_are_read_as_metadata_not_value_targets():
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': [
        {'name': f'field_{i}', 'description': 'SYNTHETIC full column metadata ' * 20}
        for i in range(180)]}
    binding = {'property_id': 'SYNTHETIC period', 'definition': {
        'description': 'SYNTHETIC quantity requires field_170 as its time convention.',
        'measurement_conditions_schema': []}}
    spec = {'target': {'main_id': 'SYNTHETIC_AQ'}, 'properties': [binding]}
    prompt = CatalogService.header_prompt(table, spec, ['field_1'])
    assert 'field_170' in visible_columns(prompt)
    assert prompt['target_columns'] == ['field_1']
    assert len(canonical(prompt)) <= MAX_HEADER_BYTES


READ_ME = '''SYNTHETIC source documentation
Byte-by-byte Description of file: measurements.dat
------------------------------------------------
 Bytes Format Units Label Explanations
------------------------------------------------
 1-10 F10.3 mag Mag Selected magnitude (1)
 12-13 A2 --- Flag Origin of magnitude (2)
------------------------------------------------
Note (1): A non-detection is an upper limit; inspect Flag.
Note (2): Zero means a limit, nine means no useful brightness.
------------------------------------------------
Byte-by-byte Description of file: unrelated.dat
 1-10 F10.3 mag Mag A different quantity (1)
Note (1): This is a different table's note.
------------------------------------------------
'''


def test_readme_local_notes_do_not_cross_tables_and_flag_metadata_is_linked():
    parsed = parse_readme(READ_ME, 'J/SYNTHETIC/v1/measurements')
    view = document_view({'parsed': parsed}, ['Mag'], ['Mag', 'Flag'])
    assert view['referenced_column_names'] == ['Flag', 'Mag']
    assert set(view['notes']) == {'1', '2'}
    assert 'different' not in str(view)
    assert view['notes']['1'][0]['line_start'] == 9
    assert view['field_descriptions']['Mag'][0]['text'].startswith(' 1-10')
    ambiguous = parse_readme(READ_ME.replace('unrelated.dat', 'measurements.sam'), 'J/SYNTHETIC/v1/measurements')
    assert ambiguous['state'] == 'table_layout_not_identified'
    unknown = parse_readme(READ_ME, 'J/SYNTHETIC/v1/missing')
    assert unknown['state'] == 'table_layout_not_identified'


def test_readme_url_requires_actual_catalog_containment_and_no_path_traversal():
    assert readme_url('J/A+A/123/45', 'J/A+A/123/45/table1').endswith('/J/A+A/123/45/ReadMe')
    for catalog, table in [('II/246', 'II/246evil/out'), ('../../etc', '../../etc/passwd'),
                           ('https://example.org', 'https://example.org/out')]:
        with pytest.raises(DomainError):
            readme_url(catalog, table)


def test_explicit_error_metadata_is_retained_without_assigned_sigma_or_role():
    plan = {'id_column': 'Name', 'properties': [{'property_id': 'SYNTHETIC', 'value_column': 'Value', 'error_columns': []}]}
    table = {'columns': [{'name': 'e_Value', 'ucd': 'stat.error;phys.size'},
                         {'name': 'E_Value', 'ucd': 'stat.error;phys.size'},
                         {'name': 'e_Other', 'ucd': 'stat.error'}, {'name': 'e_Wrong', 'ucd': 'phys.size'}]}
    kept, checks = retain_declared_errors(plan, table)
    assert kept['properties'][0]['error_columns'] == ['e_Value', 'E_Value']
    assert all(c['semantic_interpretation_granted'] is False for c in checks)
    assert plan['properties'][0]['error_columns'] == []


def test_concurrent_readme_receipts_share_identical_bytes_and_changes_are_not_merged():
    acquired = {'state': 'acquired', 'artifact_ref': {'content_sha256': 'SYNTHETIC-one'}, 'metadata': {'attempt_id': 'one'}}
    first, write, conflict = select_cached_document(None, acquired)
    assert write and not conflict and first['revision'] == 1
    same, write, conflict = select_cached_document(first, {**acquired, 'metadata': {'attempt_id': 'two'}})
    assert same == first and not write and not conflict
    changed, write, conflict = select_cached_document(first, {**acquired, 'artifact_ref': {'content_sha256': 'SYNTHETIC-two'}})
    assert changed == first and not write and conflict
    recovered, write, conflict = select_cached_document({'state': 'unavailable', 'revision': 1}, acquired)
    assert write and not conflict and recovered['revision'] == 2
    assert select_cached_document(recovered, {'state': 'unavailable'})[0] == recovered


def test_actual_coordinate_group_descriptions_are_not_changed_by_prompt_partition():
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': [
        {'name': f'field_{i}', 'description': 'Complete synthetic definition ' * 100} for i in range(50)]}
    before = deepcopy(table)
    CatalogService.header_prompt(table, {'target': {'main_id': 'SYNTHETIC_AQ'}, 'properties': []}, ['field_3'])
    assert table == before


@pytest.mark.parametrize('mode', ['complete', 'malformed', 'transport', 'format_then_remote', 'authority_changed'])
def test_shared_followup_bound_and_independent_group_survives_failed_context(mode):
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': [
        {'name': f'c{i}', 'description': 'Complete synthetic source definition ' * 20} for i in range(120)]}
    table['columns'][0].update(name='Name', ucd='meta.id;meta.main')
    targets = ['c1', 'c2']
    spec = {'target': {'main_id': 'SYNTHETIC_AQ'}, 'properties': [{'property_id': 'length', 'definition': {'description': 'SYNTHETIC whole length'}, 'output_profile': {}}]}
    plan = {'id_column': 'Name', 'identity_namespace': None, 'limitations': [],
        'properties': [{'property_id': 'length', 'value_column': c, 'error_columns': errors,
            'source_unit': 'm', 'source_representation': 'linear'} for c, errors in [('c1', ['c90']), ('c2', [])]],
        'column_resolution': [{'column': c, 'role': 'value', 'reason': 'SYNTHETIC stated role'} for c in targets]}
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        if len(calls) == 1 and mode == 'format_then_remote':
            return {**plan, 'limitations': 'wrong type'}, {'attempt_id': 'SYNTHETIC first malformed'}
        if len(calls) == 2:
            if mode == 'malformed':
                return {}, {'attempt_id': 'SYNTHETIC failed context'}
            if mode == 'transport':
                raise httpx.ConnectError('SYNTHETIC lost connection')
            if mode == 'authority_changed':
                raise DomainError('PROFILE_QUALIFICATION_CHANGED', 'SYNTHETIC authority changed')
        return deepcopy(plan), {'attempt_id': 'SYNTHETIC ' + str(len(calls))}

    async def run():
        return await interpret_header(table, spec, targets, prompt_factory=CatalogService.header_prompt,
            validate=CatalogService.validate_column_plan, ask=ask)
    if mode == 'authority_changed':
        with pytest.raises(DomainError, match='authority changed'):
            asyncio.run(run())
        return
    result = asyncio.run(run())
    assert len(calls) == 2 and result['shared_followup_used'] is True
    assert [m['value_column'] for m in result['plan']['properties']] == (['c1', 'c2'] if mode == 'complete' else ['c2'])
    if mode != 'format_then_remote':
        assert 'c90' in visible_columns(calls[1])
    else:
        assert 'c90' not in visible_columns(calls[1])


@pytest.mark.parametrize('second_invalid', [False, True])
def test_initial_transport_retry_consumes_shared_ceiling_and_has_no_third_call(second_invalid):
    table = {'table_id': 'SYNTHETIC/v1/table', 'columns': [
        {'name': f'c{i}', 'description': 'SYNTHETIC full metadata ' * 40} for i in range(120)]}
    table['columns'][0].update(name='Name', ucd='meta.id;meta.main')
    spec = {'target': {'main_id': 'SYNTHETIC_AQ'}, 'properties': [{'property_id': 'length', 'definition': {'description': 'SYNTHETIC whole length'}}]}
    plan = {'id_column': 'Name', 'identity_namespace': None, 'limitations': [], 'properties': [
        {'property_id': 'length', 'value_column': 'c1', 'error_columns': ['c90'],
         'source_unit': 'm', 'source_representation': 'linear'}],
        'column_resolution': [{'column': 'c1', 'role': 'value', 'reason': 'SYNTHETIC original definition'}]}
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise DomainError('INCOMPLETE_MODEL_RESPONSE', 'SYNTHETIC incomplete transport')
        return ({} if second_invalid else deepcopy(plan)), {'attempt_id': 'SYNTHETIC second'}

    async def run():
        return await interpret_header(table, spec, ['c1'], prompt_factory=CatalogService.header_prompt,
                                      validate=CatalogService.validate_column_plan, ask=ask)
    if second_invalid:
        with pytest.raises(DomainError):
            asyncio.run(run())
    else:
        result = asyncio.run(run())
        assert result['shared_followup_used'] and not result['plan']['properties']
        assert any(g['reason'] == 'required_field_metadata_not_read' for g in result['gaps'])
    assert len(calls) == 2
