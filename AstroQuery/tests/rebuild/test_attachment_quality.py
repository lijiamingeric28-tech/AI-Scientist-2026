"""Regression coverage for scoped attachment semantics and raw row checks."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science import structured_quality as qa
from astroquery_ai.science.archive_comparison import different_observations, observation_series_review


COLUMNS = [
    {'name': 'Object', 'ucd': 'meta.id;meta.main', 'description': 'Object identifier'},
    {'name': 'Epoch', 'ucd': 'time.epoch', 'unit_text': 'd', 'description': 'Time of observation'},
    {'name': 'Band', 'ucd': 'em.opt', 'description': 'Passband'},
    {'name': 'Flux', 'ucd': 'phot.flux', 'unit_text': 'Jy', 'description': 'Observed flux density'},
    {'name': 'Error', 'ucd': 'stat.error;phot.flux', 'unit_text': 'Jy', 'description': 'Independent error'},
]


def proposal(row, index):
    return {'column': 'Flux', 'row': index, 'representation': 'linear', 'unit': 'Jy', 'limit': 'none',
        'value': {'kind': 'real', 'value': row['Flux']}, 'raw_value': row['Flux'],
        'errors': [{'location': 'Error', 'kind': 'symmetric_delta', 'interpretation_state': 'parsed',
            'source_unit': 'Jy', 'raw_text': row['Error'], 'values': {'delta': row['Error']}}] if row['Error'] else [],
        'conditions': [{'key': 'source_field:' + k, 'value': row[k], 'state': 'known', 'raw_text': k + ': ' + row[k]}
            for k in ('Epoch', 'Band')]}


def test_mechanical_witness_preserves_zero_and_negative_values():
    row = {'Object': 'Target', 'Epoch': '1.0', 'Band': 'R', 'Flux': '-1.50', 'Error': '0.00'}
    scope = qa.TableScope(reusable=True, table_role='observation', error_columns=['Error'],
        context_columns=['Epoch', 'Band'], limit='none', reason='Same source columns')
    item = proposal(row, 0)
    assert qa.scalar_check(item, row, COLUMNS, scope)
    for changes in ({'errors': []}, {'limit': 'upper'}, {'unit': 'mJy'}, {'conditions': item['conditions'][:1]}):
        assert not qa.scalar_check({**item, **changes}, row, COLUMNS, scope)
    assert qa.transcription_problem({**item, 'value': {'kind': 'real', 'value': '1.50'}}, row, COLUMNS) == 'main_cell_value_mismatch'
    missing = {**row, 'Error': '', 'Flux': '0'}
    assert qa.scalar_check(proposal(missing, 1), missing, COLUMNS, scope)
    assert not qa.scalar_check(proposal(missing, 1), missing, COLUMNS, scope.model_copy(update={'limit': 'upper'}))
    absent = {**item, 'conditions': []}
    restored = qa.complete_conditions(absent, row, COLUMNS, scope)
    assert qa.scalar_check(restored, row, COLUMNS, scope) and absent['conditions'] == []
    assert qa.time_coordinate({'name': 'BJD', 'unit_text': 'd'})
    assert not qa.time_coordinate({'name': 'BJD', 'unit_text': None})


def test_scope_changes_for_target_schema_hdu_file_or_property():
    source = {'artifact': {'sha256': 'original'}, 'table_id': 't', 'association': {'hdu': 1},
        'metadata': {'columns': COLUMNS}}
    target = {'target_id': 'target'}
    binding = {'property_id': 'flux', 'definition_version': 1}
    baseline = qa.table_scope_basis(source, target, binding, 'model')
    for changed in ({**source, 'artifact': {'sha256': 'updated'}}, {**source, 'association': {'hdu': 2}},
            {**source, 'metadata': {'columns': [{**COLUMNS[0], 'description': 'Different meaning'}, *COLUMNS[1:]]}}):
        assert qa.table_scope_basis(changed, target, binding, 'model') != baseline
    assert qa.table_scope_basis(source, {'target_id': 'other'}, binding, 'model') != baseline
    assert qa.table_scope_basis(source, target, {**binding, 'definition_version': 2}, 'model') != baseline
    assert qa.explicit_model_source({'columns': COLUMNS, 'description': 'Pulsation model data for the star'}, 'Flux')
    assert not qa.explicit_model_source({'columns': COLUMNS, 'description': 'Model comparison and observations'}, 'Flux')
    assert different_observations(['s', 'JD', '100', 'em.opt.B'], ['s', 'JD', '100', 'em.opt.V'])
    assert not different_observations(['s', 'JD', '100', None], ['p', 'JD', '101', None])
    assert observation_series_review({'1': ['s', 'JD', '100', 'em.opt.B'],
        '2': ['s', 'JD', '100', 'em.opt.V'], '3': ['s', 'JD', '100', 'em.opt.B'],
        '4': ['s', 'JD', '101', 'em.opt.B']}) == {'1', '3'}


@pytest.mark.parametrize('size', [6, 10001])
def test_every_row_checked_and_one_call_per_semantic_scope(tmp_path, monkeypatch, size):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC table')['task_id']
    target = {'target_id': 'object', 'main_id': 'Target', 'aliases': []}
    source = {'artifact': {'artifact_id': 'original', 'sha256': 'sha'}, 'table_id': 't', 'association': {'hdu': 1},
        'metadata': {'columns': COLUMNS, 'description': 'Observations'}, 'source_id': 's', 'work_id': 'p'}
    rows = [{'Object': 'Target', 'Epoch': str(i), 'Band': 'R' if i % 2 else 'B',
        'Flux': str(-i), 'Error': '0.1'} for i in range(size)]
    proof = {'source_rows': list(range(size)), 'target_id': 'object', 'target_content_sha256': content_hash(target),
        'table_id': 't', 'source_artifact_ref': {'id': 'original', 'content_sha256': 'sha'}, 'id_column': 'Object'}
    ref = {'id': 'proof', 'version': 1, 'content_sha256': content_hash(proof)}
    candidates = []
    for i, row in enumerate(rows):
        raw = canonical({'cells': row, 'columns': COLUMNS}).decode()
        candidates.append({'candidate_id': str(i), 'assembly_context': {'object_binding_ref': ref},
            'proposal': {**proposal(row, i), 'source_quote': raw},
            'evidence': {'source_id': 's', 'locator': {'row': i, 'column': 'Flux', 'table': 't'},
                'artifact_ref': {'id': 'original', 'content_sha256': 'sha'}, 'raw_text': raw}})
    candidates[1]['proposal']['errors'] = []
    candidates[-1]['evidence']['locator']['row'] = 0
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open')
        repo.put_object(conn, tid, 'attachment', 'a', 1, source)
        repo.put_object(conn, tid, 'object_match', 'proof', 1, proof)
        repo.enqueue(conn, tid, 'M07', 'quality_verify', {'root_id': 'qa'})
    job = repo.claim_job('test', lease_seconds=600)
    calls, applied, exceptions = [], {}, []

    class Original:
        def __init__(self, *args):
            pass

        async def read_rows(self, table_id):
            return {'resources': [{'tables': [{'columns': COLUMNS, 'rows': rows, 'source_row_numbers': list(range(size))}]}]}

    async def semantics(service, job, spec, binding, source, members, regime, profile, key, science):
        calls.append(regime['cells']['Band'])
        return qa.TableReply.model_validate({
            'scope': {'reusable': True, 'table_role': 'observation', 'error_columns': ['Error'],
                'context_columns': ['Epoch', 'Band'], 'limit': 'none', 'reason': 'Verified column definitions'},
            'item': {'item_id': 'I1', 'subject': 'target', 'quantity_relation': 'same', 'reported_quantity': 'flux',
                'subject_scale': 'target', 'result_role': 'reported_result', 'native_representation': 'linear',
                'value_match': 'exact', 'unit_match': 'exact', 'errors_match': 'exact', 'evidence_columns': ['Flux'],
                'checked_ids': ['E1'], 'reason': 'Actual saved column'},
        }), {'attempt_id': key}, {}

    async def apply(service, job, spec, binding, source, candidate, item, receipt, **kwargs):
        assert candidate['candidate_id'] not in applied
        applied[candidate['candidate_id']] = kwargs

    async def fallback(service, job, spec, binding, source, batch, *args, **kwargs):
        exceptions.extend(c['candidate_id'] for c in batch)

    monkeypatch.setattr(qa, 'LocalAttachmentCatalog', Original)
    monkeypatch.setattr(qa, 'check_scope', semantics)
    monkeypatch.setattr(qa, 'apply_item', apply)
    monkeypatch.setattr(qa, '_verify_batch', fallback)
    monkeypatch.setattr(qa, '_catalog_input', lambda *a: ({}, {}))
    asyncio.run(qa.verify_table(SimpleNamespace(repo=repo, app=None), job, {'target': target},
        {'property_id': 'flux'}, source, candidates, SimpleNamespace(model='test')))
    assert len(calls) == 2
    assert len(applied) == size - 1
    assert exceptions == ['1']
    assert applied[str(size - 1)]['missing_reason'] == 'attachment_original_binding_mismatch'
    assert applied['0']['table_checks']['row_check']['locator']['row'] == 0


def test_shared_correction_rechecks_only_the_question_scope(tmp_path):
    from astroquery_ai.runtime.reviews import ReviewAnswer, ReviewService
    from astroquery_ai.science.processing.assessment import scientific_candidate_question
    from astroquery_ai.science.processing.review_application import apply_review_once

    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC shared correction')['task_id']
    reviews = ReviewService(repo)
    source = {'kind': 'official_attachment', 'metadata': {'columns': COLUMNS}}
    definition = {'name_cn': '流量', 'measurement_conditions_schema': []}
    spec = {'spec_hash': 'frozen'}
    observed = []

    def assemble(*, proposal, **kwargs):
        observed.append((proposal.row, proposal.raw_value, proposal.unit))
        assert kwargs['human_answer_ref']
        return {'state': 'admitted'}

    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open')
        questions = []
        for index, scope in enumerate(('shared', 'shared', 'other-band')):
            token = str(index - 1)
            issue = {'issue_kind': 'unit_semantics', 'issue_key': 'table-unit',
                'question': '请根据原表列定义核对流量单位。', 'undecided_fact': '原表列的单位需要确认。',
                'scope_kind': 'column_definition', 'scope_columns': ['Flux'], 'support_columns': ['Flux'],
                'counter_columns': [],
                'choices': [{'action': 'correct', 'label': '依据列定义修正单位', 'impact': '单位修正'},
                            {'action': 'unable', 'label': '保留未决', 'impact': '原值保留'}],
                'correction_types': ['correct_unit']}
            evidence = {'evidence_id': f'original-{index}', 'raw_text': f'Flux [{token}] Jy'}
            evidence['content_sha256'] = digest(evidence)
            ref = repo.put_object(conn, tid, 'evidence', evidence['evidence_id'], 1, evidence)
            candidate = {'candidate_id': f'candidate-{index}', 'evidence_ref': ref, 'proposal': {
                'property_id': 'flux', 'value': {'kind': 'real', 'value': token}, 'raw_value': token,
                'unit': None, 'representation': 'linear', 'source_quote': evidence['raw_text'], 'page': None,
                'row': index, 'column': 'Flux', 'subject_role': 'target', 'result_role': 'reported_result',
                'location_kind': 'catalog_cell', 'limit': 'none', 'errors': [], 'conditions': [],
                'ambiguity': None, 'catalog_review_issue': issue},
                'assembly_context': {'owner': 'M03', 'source': source,
                    'quality_verification': {'row_check': {'state': 'verified'}, 'shared_table_check_ref': {'id': scope}}}}
            repo.put_object(conn, tid, 'candidate', candidate['candidate_id'], 1, candidate)
            questions.append(reviews.register(conn, tid, scientific_candidate_question(candidate, definition, spec)))
    assert questions[0]['review_id'] == questions[1]['review_id'] != questions[2]['review_id']
    question = questions[1]
    answer = ReviewAnswer(task_id=tid, review_id=question['review_id'], review_revision=question['revision'],
        basis_hash=question['basis_hash'], client_request_id='fix-shared-unit', action='correct',
        reason='原表列声明为 Jy。', correction={'type': 'correct_unit', 'unit': 'Jy', 'representation': 'linear',
        'representation_parameters': {'kind': 'linear'}, 'evidence_ref': question['evidence_refs'][0], 'quote': 'Jy'})
    first = reviews.answer(answer)
    assert reviews.answer(answer) == first
    job = repo.claim_job('test', lease_seconds=600)
    service = SimpleNamespace(repo=repo, extractor=SimpleNamespace(assemble=assemble), commit_candidates=lambda *a: None)
    asyncio.run(apply_review_once(service, job))
    assert observed == [(0, '-1', 'Jy'), (1, '0', 'Jy')]
    with repo.read() as conn:
        saved = reviews.list(conn, tid)
        assert [x['status'] for x in saved] == ['resolved', 'pending']
        assert saved[0]['application']['postcheck'] == 'passed'


def test_resumed_attachment_exception_exhaustion_closes_only_its_batch(monkeypatch):
    from astroquery_ai.runtime.calls import ModelProfile
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.science import unified_quality

    async def unavailable(*args, **kwargs):
        raise DomainError('ATTEMPT_LIMIT', 'Already tried this persisted batch')

    applied = []

    async def apply(*args, **kwargs):
        applied.append(kwargs)

    monkeypatch.setattr(unified_quality, 'apply_item', apply)
    candidate = {'candidate_id': 'candidate-1'}
    row_check = {'row_check': {'state': 'verified'}}
    receipt = asyncio.run(unified_quality._verify_batch(SimpleNamespace(steps=SimpleNamespace(model=unavailable)),
        {'task_id': 'task'}, {}, {}, {'kind': 'official_attachment'}, [candidate], {'items': [{'item_id': 'I1'}]},
        None, None, [], [], ModelProfile(model='qwen3.7-plus', version='test'), 'root',
        catalog_material={}, table_row_checks={'candidate-1': row_check}))
    assert receipt['checked'] == 0
    assert applied[0]['missing_reason'] == 'quality_exception_retry_budget_exhausted'
    assert applied[0]['table_checks'] == row_check
