"""Exercise the ordinary M08 job, including rejected model arithmetic."""
import asyncio
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.calls import ModelProfile
from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.science.workflow.quality_service import QualityService
from tests.rebuild.factories import measurement


@pytest.mark.parametrize('logarithmic', [False, True])
def test_verified_simple_conversion_needs_no_model_and_wrong_complex_arithmetic_is_recomputed(tmp_path, logarithmic):
    async def run():
        app = Application(tmp_path, allow_synthetic=True)
        repo = app.repository
        tid = repo.create_task('SYNTHETIC ordinary normalization service')['task_id']
        source = measurement(value='2')
        source.update(task_id=tid, unit='dex' if logarithmic else 'km', representation='log10' if logarithmic else 'linear')
        source['content_sha256'] = content_hash(source)
        source_rep = {'kind': 'log10', 'reference_value': '1', 'reference_unit': 'm'} if logarithmic else {'kind': 'linear'}
        policy = {'policy_id': 'SYNTHETIC same quantity', 'version': 1, 'allowed_operators': ['linear', 'log10']}
        policy['content_sha256'] = content_hash(policy)
        output = {'profile_id': 'SYNTHETIC output', 'version': 1, 'unit': {'canonical_symbol': 'm'},
            'representation': {'kind': 'linear'}, 'conversion_policy_ref': {
                'id': policy['policy_id'], 'version': 1, 'content_sha256': policy['content_sha256']}}
        output['content_sha256'] = content_hash(output)
        spec = {'properties': [{'property_id': source['property_ref']['id'], 'output_profile': output,
            'definition': {'quantity_key': 'SYNTHETIC length'}}], 'dependencies': [], 'registry_release': {'id': 'SYNTHETIC registry'}}
        with repo.transaction() as conn:
            query = repo.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC query', 1, spec)
            repo.mutate_task(conn, tid, lifecycle='queued', science_state='open', query_ref=canonical(query).decode())
            repo.put_object(conn, tid, 'measurement', source['measurement_id'], 1, source)
            repo.put_object(conn, tid, 'interpretation', source['interpretation_ref']['id'], 1,
                {'proposal': {'representation_parameters': source_rep, 'source_quote': 'SYNTHETIC exactly specified scalar'}})
            repo.put_object(conn, tid, 'context', source['context_ref']['id'], 1, {'conditions': [], 'source_statements': []})
            repo.enqueue(conn, tid, 'M08', 'normalize', {'measurement_id': source['measurement_id'], 'source_hash': source['content_sha256']})
        app.registry = SimpleNamespace(load=lambda release: {'data': {'conversion-policies': [policy]}})
        calls = []

        async def model(*args, **kwargs):
            calls.append(kwargs)
            return {'value_typed': {'kind': 'real', 'value': '999'}, 'components': []}, {'attempt_id': 'SYNTHETIC wrong math'}

        context = SimpleNamespace(app=app, repo=repo, steps=SimpleNamespace(model=model), extractor=None,
            spec=lambda conn, task: spec, model_profile=lambda owner, **kwargs: ModelProfile(model='qwen3.8-flash', **kwargs))
        job = repo.claim_job('SYNTHETIC worker')
        await QualityService(context).normalize(job)
        with repo.read() as conn:
            selected = repo.objects(conn, tid, 'derived')
            assert len(selected) == 1 and selected[0]['status'] == 'ready'
            from decimal import Decimal
            assert Decimal(selected[0]['value_typed']['value']) == (Decimal(100) if logarithmic else Decimal(2000))
            checks = repo.objects(conn, tid, 'normalization_proposal_check')
            receipts = repo.objects(conn, tid, 'processing_receipt')
            assert len(receipts) == 1 and receipts[0]['postcheck'] == 'passed'
            if logarithmic:
                assert len(calls) == len(checks) == 1
                assert checks[0]['status'] == 'numeric_recomputed'
                assert checks[0]['model_numbers_adopted'] is False
                assert receipts[0]['model_proposal_checks'] == checks
            else:
                assert calls == checks == []
            assert repo.object(conn, tid, 'measurement', source['measurement_id']) == source
            assert not repo.objects(conn, tid, 'review_answer')
        assert app.budget.summary()['committed_micros'] == 0

    asyncio.run(run())
