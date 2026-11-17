"""Routing/coverage regressions; synthetic data are never scientific evidence."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.calls import ModelProfile
from astroquery_ai.runtime.codec import loads
from astroquery_ai.science import archive_comparison as archive
from astroquery_ai.science import structured_quality as qa


@pytest.mark.parametrize('size', [2, 24])
@pytest.mark.parametrize('failed_cross', [False, True])
def test_cross_sources_keep_full_navigation_and_selected_originals(monkeypatch, size, failed_cross):
    labels = {f'R{i}': {'measurement_id': f'm{i}', 'revision': 1, 'content_sha256': str(i)}
              for i in range(size)}
    evidence = {f'E{i}': {'record': f'R{i}', 'source_id': f's{i % 2}', 'locator': {'row': i},
        'ref': {'id': f'e{i}', 'version': 1, 'content_sha256': str(i)}} for i in range(size)}
    body = {'schema': archive.ComparisonReply.model_json_schema(), 'property': {}, 'answered_questions': [],
        'instruction': 'SYNTHETIC inspect actual originals', 'items': [
            {'record': f'R{i}', 'same_source_key': f's{i % 2}', 'source_label': f'Synthetic source {i % 2}',
             'native': {'raw_value': str(i), 'unit': 's', 'uncertainty': {'components': []}},
             'processed': None, 'context': [], 'evidence': [f'E{i}'], 'reported_references': [],
             'result_role': 'reported_result', 'observation_coordinate': [f's{i % 2}', 'JD', str(i // 2), 'V']}
            for i in range(size)],
        'evidence': {k: {**{a: b for a, b in v.items() if a != 'ref'}, 'text_ref': k} for k, v in evidence.items()},
        'source_texts': {k: 'SYNTHETIC original source table and source notes' for k in evidence}}
    saved, calls = [], []

    @contextmanager
    def tx():
        yield None

    repo = SimpleNamespace(read=tx, transaction=tx, validate_lease=lambda *a: None,
        put_object=lambda *a: saved.append(a[-1]), finish_job=lambda *a: None, objects=lambda *a: [])
    monkeypatch.setattr(archive, 'comparison_input', lambda *a: (body, labels, evidence))

    async def model(*args, **kw):
        import httpx
        value = loads(kw['messages'][0]['content'])
        calls.append(value)
        if 'all_record_index' in value:
            assert {v['record'] for v in value['all_record_index']['items']} == set(labels)
            return {'index_members': list(labels), 'evidence_groups': [['R0', 'R1']]}, {'attempt_id': 'navigation'}
        own = [v['record'] for v in value['items']]
        assert own and {'R0', 'R1'} <= set(own)
        assert value['source_texts']  # The index alone cannot judge anything.
        if failed_cross:
            raise httpx.ReadTimeout('SYNTHETIC original review unavailable')
        return {'checked_members': own, 'duplicates': [], 'suspicions': [], 'interpretation_issues': []}, {'attempt_id': 'originals'}

    service = SimpleNamespace(repo=repo, spec=lambda *a: {}, steps=SimpleNamespace(model=model),
        model_profile=lambda *a, **k: ModelProfile('qwen3.7-plus', max_input_tokens=96000))
    asyncio.run(archive.compare_results(service, {'task_id': 'synthetic', 'payload': {
        'property_id': 'p', 'input_hash': 'hash', 'measurement_refs': []}}))
    report = saved[-1]
    assert report['state'] == ('partial' if failed_cross else 'checked')
    assert report['coverage']['mode'] != 'verified_observation_series'
    if size == 24:
        assert sum('all_record_index' in c for c in calls) == 1
        assert all(len(c['items']) == 2 for c in calls if 'items' in c)
        assert len(calls) == (3 if failed_cross else 2)
        assert report['coverage']['uncovered_cross_window_scope'] is failed_cross
    else:
        assert all(len(c['items']) == 2 for c in calls)


@pytest.mark.parametrize('invalid', ['missing_rule', 'wrong_token', 'invented_quote', 'not_checked', 'numeric_regime'])
def test_shared_quality_code_requires_exact_source_bound_rule(invalid):
    candidate = {'assembly_context': {'literal_transcription': {'pending_flag_columns': ['Q']}}}
    regime = {'cells': {'Q': ['literal', '0']}}
    scope = qa.TableScope(reusable=True, table_role='observation', error_columns=[], context_columns=['Q'],
        limit='none', reason='Synthetic original definitions', flag_rules=[{
            'column': 'Q', 'raw_token': '0', 'evidence_id': 'E1', 'source_quote': '0 = reported detection'}])
    result = SimpleNamespace(scope=scope, item=SimpleNamespace(checked_ids=['E1']))
    materials = {'E1': {'text': 'SYNTHETIC quality codes: 0 = reported detection; 9 = unknown'}}
    assert qa.verified_flag_rules(candidate, regime, result, materials)
    if invalid == 'missing_rule':
        scope.flag_rules = []
    elif invalid == 'wrong_token':
        scope.flag_rules[0].raw_token = '9'
    elif invalid == 'invented_quote':
        scope.flag_rules[0].source_quote = '0 = always trustworthy'
    elif invalid == 'not_checked':
        result.item.checked_ids = []
    else:
        regime['cells']['Q'] = ['numeric']
    assert not qa.verified_flag_rules(candidate, regime, result, materials)


def test_no_original_evidence_window_is_sent_for_empty_local_remainder():
    plan = archive.plan_comparison_inputs({'items': [], 'source_contexts': {}}, ModelProfile('qwen3.7-plus'))
    assert plan['windows'] == [] and plan['global_index']['items'] == []


def test_column_exclusion_survives_restart_without_another_header_call(tmp_path, monkeypatch):
    from copy import deepcopy
    from astroquery_ai.runtime.codec import digest
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.storage import ArtifactStore
    from astroquery_ai.science.catalog import extraction

    repo = Repository(tmp_path / 'db')
    tid = repo.create_task('SYNTHETIC interrupted column exclusion')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open')
        repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': 'synthetic'})
    job = repo.claim_job('test', task_id=tid, lease_seconds=600)
    table = {'table_id': 'synthetic', 'columns': [{'name': 'Difference', 'datatype': 'double',
        'unit_text': 'mag', 'description': 'Target minus reference, not fifteen-day decline'}]}
    raw = b'SYNTHETIC immutable original schema'
    schema = {'response_sha256': digest(raw.decode()), 'resources': [{'tables': [table]}]}
    spec = {'properties': [{'property_id': 'decline', 'output_profile': {}}]}
    mapping = {'property_id': 'decline', 'value_column': 'Difference', 'quantity_match': 'different'}
    plan = {'id_column': None, 'identity_namespace': None, 'properties': [mapping]}
    header = {'plan': plan, 'gaps': [], 'column_resolution': [{'column': 'Difference', 'role': 'value'}],
        'receipt': {'attempt_id': 'already-paid'}, 'metadata_visible_columns': ['Difference'],
        'shared_followup_used': True, 'source_preservation_checks': [], 'quantity_recheck': None}
    calls = []

    async def interpret(*args, **kwargs):
        calls.append(True)
        return deepcopy(header)

    async def document(*args):
        return {}

    service = SimpleNamespace(repo=repo, spec=lambda *a: spec, steps=SimpleNamespace(http=lambda *a: None),
        app=SimpleNamespace(artifacts=ArtifactStore(tmp_path / 'artifacts', repo)),
        discovered_schema=lambda *a: (schema, raw, {}), catalog_document=document,
        header_prompt=lambda *a: {}, validate_column_plan=lambda *a: None)
    monkeypatch.setattr(extraction, 'interpret_header', interpret)
    finish = repo.finish_job

    def interrupted(*args):
        raise RuntimeError('SYNTHETIC process interruption after paid header checkpoint')

    monkeypatch.setattr(repo, 'finish_job', interrupted)
    with pytest.raises(RuntimeError, match='interruption'):
        asyncio.run(extraction.extract_catalog(service, job))
    with repo.read() as conn:
        saved = repo.object(conn, tid, 'catalog_column_plan', job['job_id'])
        assert saved['plan']['properties'] == []
        assert saved['interpreted_plan']['properties'] == [mapping]
        assert saved['dimensional_rejections'][0]['reason'] == 'explicit_different_source_measurand'
    monkeypatch.setattr(repo, 'finish_job', finish)
    asyncio.run(extraction.extract_catalog(service, job))
    with repo.read() as conn:
        coverage = repo.object(conn, tid, 'coverage', job['job_id'])
        assert coverage['reason'] == 'original_column_definitions_exclude_planned_quantities'
        assert coverage['raw_source_preserved'] is True
        assert coverage['dimensional_rejections'] == saved['dimensional_rejections']
        assert repo.object(conn, tid, 'catalog_column_plan', job['job_id']) == saved
    assert len(calls) == 1


def test_shared_scope_and_completed_row_witnesses_survive_interruption(tmp_path, monkeypatch):
    from astroquery_ai.runtime.codec import canonical, content_hash
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.science.catalog.literal_rows import literal_proposal

    repo = Repository(tmp_path / 'db')
    tid = repo.create_task('SYNTHETIC shared scope restart')['task_id']
    target = {'target_id': 'target', 'main_id': 'Target', 'aliases': []}
    columns = [{'name': 'Flux', 'datatype': 'double', 'unit_text': 'Jy', 'ucd': 'phot.flux'},
               {'name': 'Q', 'datatype': 'char', 'description': '0 = reported detection'}]
    rows = [{'Flux': str(i) + '.000', 'Q': '0'} for i in range(6)]
    source = {'kind': 'official_attachment', 'source_id': 'source', 'table_id': 't', 'work_id': 'w',
        'artifact': {'artifact_id': 'original', 'sha256': 'sha'}, 'association': {},
        'metadata': {'columns': columns}}
    proof = {'source_rows': list(range(6)), 'target_id': 'target', 'target_content_sha256': content_hash(target),
        'table_id': 't', 'source_artifact_ref': {'id': 'original', 'content_sha256': 'sha'}}
    ref = {'id': 'proof', 'version': 1, 'content_sha256': content_hash(proof)}
    candidates = []
    for i, row in enumerate(rows):
        p = literal_proposal(row, i, columns, {'property_id': 'flux', 'value_column': 'Flux',
            'quantity_match': 'exact', 'source_representation': 'linear', 'source_unit': 'Jy',
            'quality_columns': ['Q']}, shared_flags=True)[0].model_dump(mode='json')
        candidates.append({'candidate_id': str(i), 'proposal': p,
            'assembly_context': {'object_binding_ref': ref, 'literal_transcription': {'pending_flag_columns': ['Q']}},
            'evidence': {'source_id': 'source', 'locator': {'table': 't', 'row': i, 'column': 'Flux'},
                'artifact_ref': {'id': 'original', 'content_sha256': 'sha'},
                'raw_text': canonical({'cells': row, 'columns': columns}).decode()}})
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open')
        repo.put_object(conn, tid, 'attachment', 'a', 1, source)
        repo.put_object(conn, tid, 'object_match', 'proof', 1, proof)
        repo.enqueue(conn, tid, 'M07', 'quality_verify', {'root_id': 'qa'})
    job = repo.claim_job('test', task_id=tid, lease_seconds=600)
    calls, applied = [], []
    materials = {'E1': {'native_id': 'column:Q', 'text': '0 = reported detection'}}

    class Original:
        def __init__(self, *args):
            pass

        async def read_rows(self, *args):
            return {'resources': [{'tables': [{'columns': columns, 'rows': rows, 'source_row_numbers': list(range(6))}]}]}

    async def scope(*args):
        calls.append(True)
        return qa.TableReply.model_validate({'scope': {'reusable': True, 'table_role': 'observation',
            'error_columns': [], 'context_columns': ['Q'], 'limit': 'none', 'reason': 'SYNTHETIC source',
            'flag_rules': [{'column': 'Q', 'raw_token': '0', 'evidence_id': 'E1', 'source_quote': '0 = reported detection'}]},
            'item': {'item_id': 'I1', 'subject': 'target', 'quantity_relation': 'same', 'reported_quantity': 'flux',
                'subject_scale': 'target', 'result_role': 'reported_result', 'native_representation': 'linear',
                'value_match': 'exact', 'unit_match': 'exact', 'errors_match': 'not_reported',
                'evidence_columns': ['Flux'], 'checked_ids': ['E1'], 'reason': 'SYNTHETIC source'}}), {'attempt_id': 'paid'}, materials

    interrupted = [False]

    async def apply(service, job, spec, binding, source, candidate, item, receipt, **kwargs):
        if len(applied) == 2 and not interrupted[0]:
            interrupted[0] = True
            raise RuntimeError('SYNTHETIC interruption after two saved row decisions')
        assert candidate['candidate_id'] not in applied
        applied.append(candidate['candidate_id'])
        with repo.transaction() as conn:
            repo.put_object(conn, tid, 'quality_decision', candidate['candidate_id'], 1, {
                'candidate_ref': {'content_sha256': content_hash(candidate)}, **kwargs['table_checks']})

    monkeypatch.setattr(qa, 'LocalAttachmentCatalog', Original)
    monkeypatch.setattr(qa, 'check_scope', scope)
    monkeypatch.setattr(qa, '_catalog_input', lambda *a: ({}, materials))
    monkeypatch.setattr(qa, 'apply_item', apply)
    service = SimpleNamespace(repo=repo, app=None)
    args = (service, job, {'target': target}, {'property_id': 'flux'}, source, candidates, SimpleNamespace(model='test'))
    with pytest.raises(RuntimeError, match='interruption'):
        asyncio.run(qa.verify_table(*args))
    asyncio.run(qa.verify_table(*args))
    assert len(calls) == 1 and len(applied) == 6
    with repo.read() as conn:
        assert len(repo.objects(conn, tid, 'attachment_quality_scope')) == 1
        decisions = repo.objects(conn, tid, 'quality_decision')
        assert len(decisions) == 6 and all(d['row_check']['state'] == 'verified' for d in decisions)
        summary = repo.object(conn, tid, 'attachment_quality_summary', job['job_id'])
        assert summary['resumed_closed_candidates'] == 2 and summary['rows_using_shared_check'] == 4
