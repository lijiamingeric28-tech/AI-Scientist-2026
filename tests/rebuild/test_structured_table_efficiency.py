"""Table-level work must not turn into one scientific guess per numeric row."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.catalog_header import interpret_header, QUANTITY_RECHECK_VERSION
from astroquery_ai.science.catalog.literal_rows import literal_proposal
from astroquery_ai.science.workflow.catalog_service import CatalogService
from astroquery_ai.science.processing.normalization import referenced_error_inputs
from astroquery_ai.science.structured_quality import row_regime, time_coordinate
from astroquery_ai.science.archive_comparison import observation_series_review, different_observations


def table_case():
    # Explicitly synthetic, including an intentionally inapplicable measurand.
    columns = [
        {'name': 'Time', 'datatype': 'double', 'unit_text': 'd', 'ucd': 'time.epoch', 'description': 'Observation time'},
        {'name': 'Band', 'datatype': 'char', 'description': 'Filter'},
        {'name': 'Difference', 'datatype': 'double', 'unit_text': 'mag', 'ucd': 'phot.mag',
         'description': 'Target minus comparison star magnitude; not a decline over a fixed interval'},
        {'name': 'e_Difference', 'datatype': 'double', 'unit_text': 'mag', 'ucd': 'stat.error;phot.mag',
         'description': 'Error in Difference'},
    ]
    table = {'table_id': 'SYNTHETIC/differential', 'description': 'SYNTHETIC observations of one target',
             'columns': columns, 'rows': [{'Time': str(i), 'Band': 'V', 'Difference': '0.000',
                                         'e_Difference': '0.0050'} for i in range(2391)]}
    spec = {'target': {'main_id': 'SYNTHETIC target'}, 'properties': [
        {'property_id': 'decline', 'definition': {'description': 'Decline over fifteen days'}}]}
    mapping = {'property_id': 'decline', 'value_column': 'Difference', 'error_columns': ['e_Difference'],
               'context_columns': ['Time', 'Band'], 'source_unit': 'mag',
               'source_representation': 'magnitude', 'quantity_match': 'unresolved'}
    plan = {'id_column': None, 'identity_namespace': None, 'properties': [mapping], 'limitations': []}
    return table, spec, plan


def interpret(table, spec, ask, **kwargs):
    return asyncio.run(interpret_header(table, spec, None, prompt_factory=CatalogService.header_prompt,
                                       validate=CatalogService.validate_column_plan, ask=ask, **kwargs))


@pytest.mark.parametrize('relation', ['different', 'exact', 'unresolved', 'omitted'])
def test_one_column_recheck_for_all_2391_rows_without_guessing(relation):
    table, spec, plan = table_case()
    original = deepcopy((table, spec, plan))
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        result = deepcopy(plan)
        if len(calls) == 2:
            if relation == 'omitted':
                result['properties'] = []
            else:
                result['properties'][0]['quantity_match'] = relation
        return result, {'attempt_id': str(len(calls))}

    result = interpret(table, spec, ask)
    assert len(calls) == 2 and result['shared_followup_used']
    assert result['quantity_recheck']['attempted']
    assert 'quantity_recheck' in calls[1]['context_completion']
    assert len(canonical(calls[1])) < 24000  # Metadata only, not 2,391 raw rows.
    mapping = result['plan']['properties'][0]
    assert mapping['quantity_match'] == ('unresolved' if relation == 'omitted' else relation)
    values = [literal_proposal(row, i, table['columns'], mapping)[0] for i, row in enumerate(table['rows'])]
    if relation == 'exact':
        assert all(values) and len({p.row for p in values}) == 2391
        assert all(p.raw_value == '0.000' and p.errors[0].raw_text == '0.0050' for p in values)
        assert values[-1].conditions[0].value == '2390'
        assert all(p.source_quality is None for p in values)  # independent QC still required
    else:
        assert not any(values)
    assert (table, spec, plan) == original


def test_recheck_preserves_independent_exact_column_and_omitted_ambiguous_pair():
    table, spec, plan = table_case()
    sibling = {**plan['properties'][0], 'property_id': 'photometry', 'quantity_match': 'exact'}
    spec['properties'].append({'property_id': 'photometry', 'definition': {'description': 'Differential photometry'}})
    plan['properties'].append(sibling)
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        # Second response improperly changes an independent exact result and
        # omits the uncertain pair. Neither is a valid column-level correction.
        reply = plan if len(calls) == 1 else {**plan, 'properties': [{**sibling, 'quantity_match': 'different'}]}
        return deepcopy(reply), {'attempt_id': str(len(calls))}

    result = interpret(table, spec, ask)
    assert result['plan']['properties'] == plan['properties']


@pytest.mark.parametrize('used, expected_calls', [(False, 1), (True, 0)])
def test_saved_paid_header_uses_only_the_remaining_call(used, expected_calls):
    table, spec, plan = table_case()
    initial = {'plan': deepcopy(plan), 'gaps': [], 'column_resolution': [], 'source_preservation_checks': [],
               'metadata_visible_columns': [c['name'] for c in table['columns']], 'shared_followup_used': used,
               'model_attempt_id': 'original-paid-header'}
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        return {**plan, 'properties': [{**plan['properties'][0], 'quantity_match': 'different'}]}, {'attempt_id': 'recheck'}

    result = interpret(table, spec, ask, initial=initial)
    assert len(calls) == expected_calls
    assert result['receipt']['attempt_id'] == ('recheck' if expected_calls else 'original-paid-header')
    assert result['quantity_recheck']['version'] == QUANTITY_RECHECK_VERSION
    assert initial['plan'] == plan


@pytest.mark.parametrize('failure', ['transport', 'format', 'authority'])
def test_failed_column_recheck_retains_uncertainty_and_has_no_third_call(failure):
    table, spec, plan = table_case()
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return deepcopy(plan), {'attempt_id': 'first'}
        if failure == 'transport':
            raise httpx.ConnectError('SYNTHETIC unavailable')
        if failure == 'format':
            return {}, {'attempt_id': 'bad'}
        raise DomainError('PROFILE_QUALIFICATION_CHANGED', 'SYNTHETIC changed authority')

    if failure == 'authority':
        with pytest.raises(DomainError, match='authority'):
            interpret(table, spec, ask)
    else:
        result = interpret(table, spec, ask)
        assert result['plan']['properties'][0]['quantity_match'] == 'unresolved'
        assert result['receipt']['attempt_id'] == 'first'
        assert result['gaps'][-1]['reason'] == 'shared_context_followup_failed'
    assert len(calls) == 2


def test_error_inputs_use_bound_versions_and_never_scan_the_whole_task(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC many-row table')['task_id']
    with repo.transaction() as conn:
        repo.put_object(conn, tid, 'unit', 'u', 1, {'unit_id': 'u', 'unit_text': 'mJy'})
        repo.put_object(conn, tid, 'unit', 'u', 2, {'unit_id': 'u', 'unit_text': 'Jy'})
        repo.put_object(conn, tid, 'error_basis', 'b', 1, {'basis_id': 'b', 'value': '1.500'})
        for i in range(100):
            repo.put_object(conn, tid, 'unit', str(i), 1, {'unit_id': str(i), 'unit_text': 's'})
    reads = []

    def lookup(conn, tid, kind, oid, version):
        reads.append((kind, oid, version))
        return repo.object(conn, tid, kind, oid, version)

    narrow = SimpleNamespace(object=lookup)  # No objects() method is available.
    record = {'uncertainty': {'components': [
        {'unit_ref': {'id': 'u', 'version': 1}, 'basis_ref': {'id': 'b', 'version': 1}},
        {'unit_ref': {'id': 'u', 'version': 1}, 'basis_ref': None},
        {'unit_ref': {'id': 'missing', 'version': 1}, 'basis_ref': None},
    ]}}
    with repo.read() as conn:
        bases, units = referenced_error_inputs(narrow, conn, tid, record)
    assert bases == {'b': '1.500'} and units == {'u': 'mJy'}
    assert len(reads) == 3
    from astroquery_ai.science.units import decimal_unit_factor
    assert decimal_unit_factor(units['u'], 'Jy') == Decimal('0.001')


def test_phase_varies_but_flags_methods_and_filters_split_quality_groups():
    columns = [
        {'name': 'F', 'datatype': 'double', 'unit_text': 'Jy'},
        {'name': 'Phase', 'datatype': 'double', 'unit_text': 'd'},
        {'name': 'Method', 'datatype': 'int'}, {'name': 'Flag', 'datatype': 'int'},
        {'name': 'Filter', 'datatype': 'char'}, {'name': 'Object', 'datatype': 'char'},
        {'name': 'CountRate', 'datatype': 'double', 'ucd': 'phot.count', 'unit_text': 'ct/s'},
        {'name': 'Color', 'datatype': 'double', 'ucd': 'phot.color', 'unit_text': 'mag'},
    ]
    p = {'column': 'F', 'errors': [], 'representation': 'linear', 'unit': 'Jy', 'limit': 'none'}
    row = {'F': '1.00', 'Phase': '-5.1', 'Method': '1', 'Flag': '0', 'Filter': 'V', 'Object': 'target',
           'CountRate': '10.00', 'Color': '0.010'}
    regime = row_regime(row, columns, p, {'Object'})
    assert row_regime({**row, 'F': '2', 'Phase': '1.1', 'CountRate': '100', 'Color': '-0.2'}, columns, p, {'Object'}) == regime
    for field, token in [('Method', '2'), ('Flag', '1'), ('Filter', 'B'), ('Object', 'other'), ('Phase', '<5')]:
        assert row_regime({**row, field: token}, columns, p, {'Object'}) != regime
    assert not time_coordinate(columns[1])  # Do not use phase as absolute JD.


def test_large_epoch_group_keeps_all_ambiguous_members_for_comparison():
    coordinates = {str(i): ['s', 'JD', '100', 'B'] for i in range(2391)}
    coordinates['new_epoch'] = ['s', 'JD', '101', 'B']
    coordinates['new_filter'] = ['s', 'JD', '100', 'V']
    review = observation_series_review(coordinates)
    assert review == {str(i) for i in range(2391)}
    assert observation_series_review({**coordinates, 'unknown': None}) is None
    assert not different_observations(['s', 'JD', '100', 'B'], ['other-source', 'JD', '101', 'B'])
    assert different_observations(coordinates['0'], coordinates['new_epoch'])
    assert different_observations(coordinates['0'], coordinates['new_filter'])


@pytest.mark.parametrize('binding_kind', ['table', 'exact_id', 'semantic_id', 'unverified'])
def test_catalogue_literal_collection_keeps_every_row_pending_independent_quality(tmp_path, binding_kind):
    from astroquery_ai.science.catalog.literal_rows import collect_literal_rows
    from astroquery_ai.science.structured_quality import single_table_candidates
    from astroquery_ai.runtime.codec import content_hash
    table, spec, plan = table_case()
    plan['properties'][0]['quantity_match'] = 'exact'
    spec['run_policy'] = {'workflow_contract': 'backend-consolidation/1',
                          'quality': {'catalog_table_review': 'shared_semantics/1'}}
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC bulk scalar')['task_id']
    proof = {'schema_version': 'ExactIdentifierBinding/1', 'id_column': 'Object',
             'relation': 'same_entity_identifier_anchor', 'measurement_subject_validation_required': True,
             'target_id': 'target', 'target_content_sha256': 'target-hash'}
    if binding_kind == 'table':
        proof = {**proof, 'schema_version': 'EvidencedTableSubjectBinding/1',
                 'source_declaration': {'scope': 'single_target_observations'}, 'model_attempt_ref': 'checked'}
    elif binding_kind == 'semantic_id':
        proof = {**proof, 'schema_version': 'EvidencedIdentifierBinding/1', 'relation': 'same_entity',
                 'checked_source_interpretation': {'state': 'accepted', 'source_column': 'Object'},
                 'model_attempt_ref': 'checked'}
    elif binding_kind == 'unverified':
        proof['measurement_subject_validation_required'] = False
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open')
        ref = repo.put_object(conn, tid, 'object_match', 'anchor', 1, proof)
        repo.enqueue(conn, tid, 'M03', 'catalog_extract', {})
    job = repo.claim_job('test', lease_seconds=600)
    with repo.transaction() as conn:
        repo.put_object(conn, tid, 'catalog_column_plan', job['job_id'], 1, {'revision': 1, 'plan': plan})
    collected = []

    def assemble(**kwargs):
        p = kwargs['proposal']
        assert p.subject_role == p.result_role == 'unresolved'
        return {'state': 'review_candidate', 'proposal': p.model_dump(mode='json'), 'assembly_context': {},
                'evidence': {'artifact_ref': {'id': 'original'}}}

    def commit(conn, tid, candidates, batch):
        collected.extend(deepcopy(candidates))

    service = SimpleNamespace(repo=repo, extractor=SimpleNamespace(assemble=assemble), commit_candidates=commit)
    kwargs = {'spec': spec, 'rows': table['rows'], 'table': table, 'job': job, 'tid': tid,
              'binding_refs': {i: ref for i in range(2391)}, 'pending_plans': [plan], 'matched': list(range(2391)),
              'attachment': None, 'source': {}, 'artifact': {'sha256': 'sha'}, 'seen_rows': set()}
    remainder = asyncio.run(collect_literal_rows(service, kwargs))
    if binding_kind == 'unverified':
        assert not collected and len(remainder[0][0]) == 2391
    else:
        assert not remainder and len(collected) == 2391
        assert {c['proposal']['row'] for c in collected} == set(range(2391))
        assert all(not c['assembly_context']['literal_transcription']['scientific_admission_granted'] for c in collected)
        candidates = [{**c, 'assembly_context': {**c['assembly_context'], 'object_binding_ref': ref}} for c in collected]
        with repo.read() as conn:
            assert single_table_candidates(repo, conn, tid, candidates)
        assert content_hash(proof) == ref['content_sha256']


@pytest.mark.parametrize('raw', ['-1', '<0.1', 'NaN', ''])
def test_shared_error_template_never_guesses_sentinel_limit_or_composite_cells(raw):
    from astroquery_ai.science.structured_quality import complete_literal_errors, TableScope
    from astroquery_ai.science.measurements.contracts import ErrorProposal
    table, _, plan = table_case()
    plan['properties'][0]['quantity_match'] = 'exact'
    row = table['rows'][0]
    p = literal_proposal(row, 0, table['columns'], plan['properties'][0])[0].model_dump(mode='json')
    rule = ErrorProposal.model_validate({**p['errors'][0], 'kind': 'symmetric_delta', 'interpretation_state': 'parsed',
        'values': {'delta': '0.0050'}, 'meaning': 'reported_error', 'reason': None})
    scope = TableScope(reusable=True, table_role='observation', error_columns=['e_Difference'],
        context_columns=['Time', 'Band'], limit='none', reason='SYNTHETIC complete evidence', error_templates=[rule])
    changed = {**row, 'e_Difference': raw}
    result = complete_literal_errors(p, changed, table['columns'], scope)
    assert result['errors'][0]['interpretation_state'] == 'unresolved'


def test_shared_error_template_preserves_precision_and_requires_quotes_for_confidence():
    from astroquery_ai.science.structured_quality import complete_literal_errors, TableScope
    table, _, plan = table_case()
    plan['properties'][0]['quantity_match'] = 'exact'
    row = table['rows'][0]
    p = literal_proposal(row, 0, table['columns'], plan['properties'][0])[0].model_dump(mode='json')
    rule = {**p['errors'][0], 'kind': 'symmetric_delta', 'interpretation_state': 'parsed',
        'values': {'delta': '0.0050'}, 'meaning': 'standard_uncertainty', 'role': 'stat',
        'level_kind': 'sigma_label', 'level_values': ['1'], 'level_raw_text': '1 sigma', 'reason': None}
    scope = TableScope(reusable=True, table_role='observation', error_columns=['e_Difference'],
        context_columns=['Time', 'Band'], limit='none', reason='SYNTHETIC complete evidence', error_templates=[rule])
    row = {**row, 'e_Difference': '0.01000'}
    p['errors'][0]['raw_text'] = '0.01000'
    p['source_references'] = [{'raw_code': 'R1', 'location': 'Ref', 'role': 'unknown',
                               'link_quote': None, 'page': None, 'block_ids': []}]
    completed = complete_literal_errors(p, row, table['columns'], scope)
    error = completed['errors'][0]
    assert error['values'] == {'delta': '0.01000'} and error['raw_text'] == '0.01000'
    assert error['role'] == 'unspecified' and error['meaning'] == 'reported_error' and error['level_kind'] is None
    assert p['errors'][0]['interpretation_state'] == 'unresolved'
    assert {k: v for k, v in completed.items() if k != 'errors'} == {k: v for k, v in p.items() if k != 'errors'}


def test_reusable_quality_verdict_requires_original_source_material_citations(monkeypatch):
    from astroquery_ai.science import structured_quality as qa
    from astroquery_ai.runtime.calls import ModelProfile
    monkeypatch.setattr(qa, '_catalog_input', lambda *args: ({}, {'E1': {'native_id': 'column:F', 'text': 'SYNTHETIC flux'}}))
    calls = []

    class Steps:
        async def model(self, execution, **kwargs):
            calls.append(kwargs)
            return {'scope': {'reusable': True, 'table_role': 'observation', 'error_columns': [],
                             'context_columns': [], 'limit': 'none', 'reason': 'SYNTHETIC column definition'},
                    'item': {'item_id': 'I1', 'subject': 'target', 'quantity_relation': 'same',
                             'reported_quantity': 'flux', 'subject_scale': 'target', 'result_role': 'reported_result',
                             'native_representation': 'linear', 'value_match': 'exact', 'unit_match': 'exact',
                             'errors_match': 'not_reported', 'evidence_columns': ['F'],
                             'checked_ids': [] if len(calls) == 1 else ['E1'], 'reason': 'SYNTHETIC checked source'}}, {'attempt_id': str(len(calls))}

    result, attempt, materials = asyncio.run(qa.check_scope(SimpleNamespace(steps=Steps()), {'task_id': 'synthetic'},
        {}, {}, {'metadata': {}, 'association': {}}, [{'proposal': {'errors': []}}],
        {'cells': {'F': ['numeric']}, 'column': 'F'}, ModelProfile(model='qwen3.7-plus', max_input_tokens=96000), 's', {}))
    assert len(calls) == 2 and result.item.checked_ids == ['E1'] and attempt['attempt_id'] == '2'
