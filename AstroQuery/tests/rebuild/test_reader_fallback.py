"""Synthetic control-flow test; real page capability is separately recorded."""
import asyncio
import base64
import pytest
from dataclasses import asdict
from types import SimpleNamespace

from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.extraction import EvidenceExtractor
from astroquery_ai.science.literature import FairReadLedger
from astroquery_ai.science.paper_admission import page_blocks
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from tests.rebuild.factories import ref
from tests.rebuild.registry_fixture import make_release


def test_single_page_protocol_fallback_retains_root_and_never_repeats_plus():
    from unittest.mock import MagicMock
    repo = MagicMock()
    conn = repo.read.return_value.__enter__.return_value
    conn.execute.return_value.fetchone.return_value = ['qwen3.8-flash']
    repo.enqueue.return_value = 'SYNTHETIC fallback job'
    service = object.__new__(PaperService)
    service.repo = repo
    service.reader_settings = lambda _: {'primary_model': 'qwen3.8-flash', 'fallback_model': 'qwen3.7-plus'}
    job = {'task_id': 'SYNTHETIC task', 'job_id': 'SYNTHETIC parent',
           'payload': {'core_pages': [5], 'work_id': 'SYNTHETIC work', 'root_id': 'SYNTHETIC root'}}
    assert service.single_scope_protocol_fallback(job, 'ValidationError')
    retry = repo.enqueue.call_args.args[-1]
    assert retry['root_id'] == 'SYNTHETIC root' and retry['parent_job_id'] == job['job_id']
    assert retry['force_plus_once'] and retry['reader_fallback_round'] == 1
    assert 'force_plus_once' not in job['payload']
    assert not service.single_scope_protocol_fallback({**job, 'payload': retry}, 'ValidationError')
    conn.execute.return_value.fetchone.return_value = ['qwen3.7-plus']
    assert not service.single_scope_protocol_fallback(job, 'ValidationError')
    assert repo.enqueue.call_count == 1


@pytest.mark.parametrize('trial_self_approved', [False, True])
@pytest.mark.parametrize('pause_verifier', [False, True])
def test_flash_empty_read_or_self_approved_trial_uses_separate_plus_judgment(tmp_path, trial_self_approved, pause_verifier):
    async def run():
        repo = Repository(tmp_path / 'SYNTHETIC runtime.sqlite3')
        tid = repo.create_task('SYNTHETIC local reader control')['task_id']
        data = make_release(tmp_path / 'SYNTHETIC registry')
        definition = data['definitions'][0]
        target = {'target_id': 'SYNTHETIC target', 'main_id': 'SYNTHETIC_AQ', 'aliases': []}
        spec = {'task_id': tid, 'spec_id': 'SYNTHETIC spec', 'target': target, 'properties': [{
            'property_id': definition['property_id'], 'definition': definition,
            'output_profile': data['output-profiles'][0]}], 'dependencies': [],
            'registry_release': {'id': 'SYNTHETIC registry'}}
        spec['spec_hash'] = digest(spec)
        artifact = {'artifact_id': 'SYNTHETIC artifact', 'sha256': digest('SYNTHETIC PDF')}
        source = {'source_id': 'SYNTHETIC source', 'kind': 'paper', 'artifact': artifact,
            'qualification_ref': ref('SYNTHETIC qualification'),
            'work': {'allowed_property_ids': [definition['property_id']], 'records': [{}]}}
        source['content_sha256'] = content_hash(source)
        text = 'SYNTHETIC_AQ synthetic whole length 0 m.'
        if trial_self_approved:
            text += ' A trial maximum of 126 m was used for the instrument.'
        index = {'page_count': 1, 'pages': [{'page': 1, 'text': text}]}
        ledger = FairReadLedger(['SYNTHETIC family'], {'SYNTHETIC family': [source['source_id']]},
                                {source['source_id']: ['SYNTHETIC family']})
        ledger.select()
        with repo.transaction() as conn:
            sr = repo.put_object(conn, tid, 'confirmed_query', spec['spec_id'], 1, spec)
            repo.mutate_task(conn, tid, query_ref=canonical(sr).decode(), lifecycle='queued', science_state='open')
            repo.put_object(conn, tid, 'source', source['source_id'], 1, source)
            repo.put_object(conn, tid, 'document_index', source['source_id'], 1, index)
            repo.put_object(conn, tid, 'read_ledger', tid, 1, asdict(ledger))
            repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': source['source_id'],
                'core_pages': [1], 'artifact_ref': artifact['artifact_id']})
        validation = tmp_path / 'validation'
        validation.mkdir()
        proof = {'complete': True, 'synthetic': True}
        (validation / 'SYNTHETIC-proof.json').write_bytes(canonical(proof))
        pilot = SimpleNamespace(applies=lambda task: task == tid, scope={
            'property_ids': [definition['property_id']], 'allowed_models': {'M06': ['qwen3.8-flash', 'qwen3.7-plus']},
            'reader_profile': {'profile_id': 'SYNTHETIC profile', 'primary_model': 'qwen3.8-flash',
                'fallback_model': 'qwen3.7-plus', 'core_batch_pages': 4,
                'property_ids': [definition['property_id']],
                'benchmark_report_hashes': {'SYNTHETIC-proof.json': digest(proof)}}})
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5uUAAAAASUVORK5CYII=')

        async def parse(*args, **kwargs):
            return png

        calls = []

        async def model(**kwargs):
            calls.append(kwargs['profile'].model)
            if kwargs.get('dispatch_guard'):
                with repo.transaction() as conn:
                    kwargs['dispatch_guard'](conn, {'attempt_id': 'SYNTHETIC attempt'})
            result = {'coverage': 'checked', 'limitations': [], 'results': []}
            if kwargs['profile'].model == 'qwen3.7-plus' or trial_self_approved:
                block = page_blocks({1: text})[0]['block_id']
                anchor = {'page': 1, 'block_ids': [block]}
                if kwargs['profile'].operation == 'paper_admission':
                    if pause_verifier:
                        from astroquery_ai.runtime.errors import DomainError
                        raise DomainError('DISPATCH_FORBIDDEN', 'SYNTHETIC user pause before verifier dispatch')
                    assert all(part['type'] == 'text' for part in kwargs['messages'][0]['content'])
                    return {'results': [{'index': 0, 'subject': 'target', 'printed_subject': 'SYNTHETIC_AQ',
                        'subject_evidence': [anchor], 'result_role': 'assumption' if trial_self_approved else 'reported_result', 'role_evidence': [anchor],
                        'quantity_match': 'exact', 'quantity_evidence': [anchor],
                        'unit_match':'exact', 'native_unit':'m', 'unit_evidence':[anchor],
                        'reason': 'SYNTHETIC126 is an instrument trial maximum, not a reported target length.'}]}, {'attempt_id': 'SYNTHETIC independent', 'operation': 'paper_admission'}
                result['results'] = [{'property_id': definition['property_id'], 'raw_value': '0',
                    'value': {'kind': 'real', 'value': '0'}, 'unit': 'm', 'representation': 'linear',
                    'source_quote': text, 'page': 1, 'row': None, 'column': None,
                    'subject_role': 'target', 'result_role': 'reported_result', 'location_kind': 'body',
                    'limit': 'none', 'errors': [], 'conditions': [], 'ambiguity': None,
                    'local_admission': {'index': 0, 'subject': 'target', 'printed_subject': 'SYNTHETIC_AQ',
                        'subject_evidence': [anchor], 'result_role': 'reported_result', 'role_evidence': [anchor],
                        'quantity_match': 'exact', 'quantity_evidence': [anchor], 'reason': 'SYNTHETIC source.'}}]
                if kwargs['profile'].model == 'qwen3.8-flash':
                    result['results'][0].update(raw_value='126', value={'kind': 'real', 'value': '126'})
            return result, {'attempt_id': 'SYNTHETIC ' + str(len(calls)), 'operation': 'paper_batch'}

        app = SimpleNamespace(root=tmp_path, repository=repo, pilot=pilot, parse_owned=parse,
            models=SimpleNamespace(json=model), _profile_state=lambda owner: 'validated')
        from astroquery_ai.runtime.storage import ArtifactStore
        app.artifacts=ArtifactStore(tmp_path/'artifacts',repo)
        context = ScienceContext(app)
        assert isinstance(context.extractor, EvidenceExtractor)
        job = repo.claim_job('SYNTHETIC worker')
        if pause_verifier:
            from astroquery_ai.runtime.errors import DomainError
            with pytest.raises(DomainError) as exc:
                await PaperService(context).extract_paper(job)
            assert exc.value.code == 'DISPATCH_FORBIDDEN'
            with repo.read() as conn:
                assert not repo.objects(conn, tid, 'candidate')
                assert not repo.objects(conn, tid, 'measurement')
                assert not conn.execute('SELECT 1 FROM reviews WHERE task_id=?', (tid,)).fetchone()
            return
        await PaperService(context).extract_paper(job)
        with repo.read() as conn:
            records = repo.objects(conn, tid, 'measurement')
            if trial_self_approved:
                assert records == []
                assert not any(c['state'] == 'review_candidate' for c in repo.objects(conn, tid, 'candidate'))
                repairs = repo.objects(conn, tid, 'reading_repair')
                assert len(repairs) == 1 and repairs[0]['reason'] == 'independent_gate_rejected_all_primary_candidates'
                assert repairs[0]['root_id'] == job['job_id']
                child = conn.execute('SELECT payload FROM jobs WHERE job_id=?', (repairs[0]['child_job_id'],)).fetchone()
                from astroquery_ai.runtime.codec import loads
                assert loads(child[0])['force_plus_once'] and loads(child[0])['reader_fallback_round'] == 1
            else:
                assert len(records) == 1 and records[0]['value']['value'] == '0'
                assert len(repo.objects(conn, tid, 'reading_repair')) == 1
                assert not repo.objects(conn, tid, 'candidate')
            assert not conn.execute('SELECT 1 FROM reviews WHERE task_id=?', (tid,)).fetchone()
            state = FairReadLedger(**repo.objects(conn, tid, 'read_ledger')[0])
            assert state.credited == {'SYNTHETIC family': 1}
        assert calls == (['qwen3.8-flash', 'qwen3.7-plus'] if trial_self_approved else ['qwen3.8-flash', 'qwen3.7-plus', 'qwen3.7-plus'])

    asyncio.run(run())
