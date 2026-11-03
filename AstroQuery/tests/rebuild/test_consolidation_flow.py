"""Controlled normal-entry regression; explicitly synthetic, zero real calls."""
import asyncio
import pytest
from uuid import uuid4
from copy import deepcopy
from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
from tests.rebuild.scenario import application,confirmed_case


@pytest.mark.parametrize('seal_seconds', [0, 120])
def test_normal_entry_unified_quality_empty_insights_and_all_serializers(tmp_path,monkeypatch,seal_seconds):
    from astroquery_ai.runtime import run_policy
    from astroquery_ai.science.results import export_validation
    ordinary_verify=export_validation.verify_formats;verified=[]
    def verify(body):
        verified.append(body['delivery_id'])
        return ordinary_verify(body)
    monkeypatch.setattr(export_validation,'verify_formats',verify)
    monkeypatch.setattr(run_policy,'NORMAL_RUN_POLICY',deepcopy(CONSOLIDATION_RUN_POLICY))
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json;calls=[]
        if seal_seconds:
            import time
            clock=time.time;offset=[0]
            monkeypatch.setattr(time,'time',lambda:clock()+offset[0])
            ordinary_claim=app.repository.claim_job
            def claim(*args,**kwargs):
                # The shared scenario normally grants 600 seconds to keep
                # synthetic integrations fast/simple. Reproduce production's
                # actual 60-second lease for this expiry regression.
                kwargs['lease_seconds']=60
                return ordinary_claim(*args,**kwargs)
            monkeypatch.setattr(app.repository,'claim_job',claim)
            ordinary_seal=app.delivery.seal
            def seal(conn,tid,**kwargs):
                delivery=ordinary_seal(conn,tid,**kwargs)
                offset[0]+=seal_seconds  # Controlled local CPU time; no real sleep.
                return delivery
            app.delivery.seal=seal
        async def respond(**kwargs):
            p=kwargs['profile'];calls.append((kwargs['owner'],p.version))
            if p.version=='metadata-terms-2':
                body=loads(kwargs['messages'][-1]['content'])
                return {'target_name_labels':[next(iter(body['verified_names']))],'core_terms':['length'],
                    'synonyms':[],'method_terms':[],'intent':'SYNTHETIC only','rewrite_useful':False}, {'attempt_id':'synthetic-terms'}
            if p.version=='unified-catalog-quality-2':
                body=loads(kwargs['messages'][0]['content'])
                return {'items':[{'item_id':row['item_id'],'subject':'target','quantity_relation':'same',
                    'reported_quantity':'SYNTHETIC whole target length','subject_scale':'whole target','result_role':'reported_result',
                    'native_representation':'linear','value_match':'exact','unit_match':'exact','errors_match':'not_reported',
                    'evidence_columns':['Length'],'checked_ids':list(body['source_materials'])[:1],'caution_ids':[],
                    'review_issue':None,'reason':'SYNTHETIC actual row and header verified'} for row in body['items']]}, {'attempt_id':'synthetic-unified'}
            if kwargs['owner']=='M11':raise AssertionError('disabled insights must never dispatch a model')
            return await ordinary(**kwargs)
        app.models.json=respond
        state,_=await confirmed_case(app,run_policy=CONSOLIDATION_RUN_POLICY)
        assert state['lifecycle']=='completed' and state['science_state']=='sealed'
        with app.repository.read() as c:
            tid=state['task_id'];delivery=app.delivery.get(c,tid)
            quality=app.repository.objects(c,tid,'quality')[0]
            insight=app.repository.objects(c,tid,'insight')[0]
            assert len(delivery['measurements'])==1 and quality['schema_version']=='TaskCompletionScore/1'
            assert quality['measurement_scores']==[] and quality['possible_points']==95
            assert insight['status']=='disabled_pending_content' and insight['units']==[]
            assert not c.execute("select 1 from jobs where task_id=? and kind in ('source_reconcile','insights')",(tid,)).fetchone()
            assert len(app.repository.objects(c,tid,'quality_decision'))==1
            assert app.repository.objects(c,tid,'delivery_serialization_check')[0]['state']=='passed'
            assert next(s for s in state['stages'] if s['id']=='insight')['status']=='not_run'
        for fmt in ('json','json_wide','csv_long','csv_wide','package'):
            exported=app.delivery.export(tid,{'operation_id':str(uuid4()),'task_id':tid,'delivery_id':delivery['delivery_id'],
                'expected_delivery_revision':1,'selection':{'mode':'all','measurement_ids':[]},'format':fmt,'export_schema_version':1})
            assert exported['selected_count']==1 and exported['snapshot_ref']==delivery['snapshot_ref']
        import httpx
        from astroquery_ai.api.http import create_app
        api=create_app(tmp_path/'data',application=app,start_worker=False,allow_synthetic=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),base_url='http://test') as client:
            base=f"/api/tasks/{tid}/deliveries/{delivery['delivery_id']}"
            response=await client.get(base+'/records');assert response.status_code==200
            assert response.json()['items'][0]['workflow_contract']=='backend-consolidation/1'
            response=await client.get(base+'/quality');assert response.status_code==200
            assert response.json()['body']['schema_version']=='TaskCompletionScore/1'
            response=await client.get(base+'/insights');assert response.status_code==200
            assert response.json()['items'][0]['status']=='disabled_pending_content'
        assert not any(owner=='M11' for owner,_ in calls)
        assert len(verified)==1  # One complete check of the final proposed body.
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['format', 'lost_token'])
def test_failed_final_format_check_rolls_back_snapshot_and_score(tmp_path,monkeypatch,failure):
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.science.results import export_validation
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json
        async def respond(**kwargs):
            if kwargs['profile'].version=='unified-catalog-quality-2':
                body=loads(kwargs['messages'][0]['content'])
                return {'items':[{'item_id':row['item_id'],'subject':'target','quantity_relation':'same',
                    'reported_quantity':'SYNTHETIC whole length','subject_scale':'whole target',
                    'result_role':'reported_result','native_representation':'linear',
                    'value_match':'exact','unit_match':'exact','errors_match':'not_reported',
                    'evidence_columns':['Length'],'checked_ids':list(body['source_materials'])[:1],
                    'caution_ids':[],'review_issue':None,'reason':'SYNTHETIC checked row'}
                    for row in body['items']]},{'attempt_id':'synthetic-quality'}
            return await ordinary(**kwargs)
        app.models.json=respond
        if failure=='format':
            monkeypatch.setattr(export_validation,'verify_formats',lambda body:{'state':'failed'})
        else:
            ordinary_seal=app.delivery.seal
            def seal(conn,tid,**kwargs):
                body=ordinary_seal(conn,tid,**kwargs)
                conn.execute("UPDATE jobs SET lease_token='foreign-owner' WHERE task_id=? AND kind='finalize' AND status='running'",(tid,))
                return body
            app.delivery.seal=seal
        with pytest.raises(DomainError,match='五格式' if failure=='format' else '资格'):
            await confirmed_case(app,run_policy=CONSOLIDATION_RUN_POLICY)
        tid=app.repository.list_tasks()[0]['task_id']
        with app.repository.read() as c:
            task=app.repository.task(c,tid)
            assert task['science_state']=='open' and task['delivery_ref'] is None
            assert app.repository.objects(c,tid,'measurement')  # Keep the actual source data.
            for kind in ('science_snapshot','delivery','quality','delivery_serialization_check'):
                assert app.repository.objects(c,tid,kind)==[]
    asyncio.run(run())


def test_scientific_local_reextract_then_simulated_answer_rechecks_and_continues(tmp_path,monkeypatch):
    from astroquery_ai.runtime import run_policy
    from astroquery_ai.runtime.reviews import ReviewAnswer
    from tests.rebuild.scenario import run_until_wait
    monkeypatch.setattr(run_policy,'NORMAL_RUN_POLICY',deepcopy(CONSOLIDATION_RUN_POLICY))
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json;checks=0;rows=0
        async def respond(**kw):
            nonlocal checks,rows
            p=kw['profile']
            if p.version=='metadata-terms-2':
                body=loads(kw['messages'][-1]['content'])
                return {'target_name_labels':[next(iter(body['verified_names']))],'core_terms':['length'],
                    'synonyms':[],'method_terms':[],'intent':'SYNTHETIC only','rewrite_useful':False},{'attempt_id':'synthetic-terms'}
            if p.version=='unified-catalog-quality-2':
                checks+=1;body=loads(kw['messages'][0]['content'])
                item={'item_id':'I1','subject':'target','quantity_relation':'same' if checks==1 else 'insufficient',
                    'reported_quantity':'SYNTHETIC whole/component length','subject_scale':'whole or component unresolved',
                    'result_role':'reported_result','native_representation':'linear','value_match':'exact',
                    'unit_match':'different' if checks==1 else 'exact','errors_match':'not_reported',
                    'evidence_columns':['Length'],'checked_ids':list(body['source_materials'])[:1],
                    'caution_ids':[],'review_issue':None,'reason':'SYNTHETIC deliberately staged science issue, not real astronomy'}
                if checks==2:
                    item['review_issue']={'issue_kind':'quantity_semantics','issue_key':'synthetic-whole-v-component',
                        'question':'SYNTHETIC：现有列说明整体与分量解释有歧义，是否采用整体解释？',
                        'undecided_fact':'SYNTHETIC evidence-grounded alternate interpretation only',
                        'scope_columns':['Length'],'support_columns':['Length'],'counter_columns':[],
                        'choices':[{'action':'confirm','label':'按整体解释','impact':'仅本合成条目'},{'action':'unable','label':'无法判断','impact':'保留未决'}],
                        'correction_types':[]}
                return {'items':[item],'limitations':[]},{'attempt_id':'synthetic-quality-'+str(checks)}
            result,receipt=await ordinary(**kw)
            if kw['owner']=='M03' and 'results' in result:
                rows+=1
                if rows==1:result['results'][0]['unit']='cm' # Deliberate extraction error; ORIGINAL remains m.
            return result,receipt
        app.models.json=respond
        state,scheduler=await confirmed_case(app,run_policy=CONSOLIDATION_RUN_POLICY)
        assert state['lifecycle']=='waiting_review' and not state['delivery_ref'] and checks==2 and rows==2
        review=next(r for r in state['reviews'] if r['status']=='pending');tid=state['task_id']
        with app.repository.transaction() as c:
            app.repository.put_object(c,tid,'query_acceptance_run',tid,1,{'schema_version':'NormalQueryAcceptance/1',
                'task_id':tid,'simulation_authorized':True,'synthetic':True})
        answer=ReviewAnswer(task_id=tid,review_id=review['review_id'],review_revision=review['revision'],
            basis_hash=review['basis_hash'],client_request_id=str(uuid4()),action='confirm',simulation=True,
            reason='SYNTHETIC：按所给原表列说明选择测试中的整体解释；不是实际天体科学审定。')
        app.reviews.answer(answer);await run_until_wait(app,scheduler)
        final=app.view(tid)
        assert final['lifecycle']=='completed' and final['science_state']=='sealed'
        assert final['reviews'][0]['application']['postcheck']=='passed'
        with app.repository.read() as c:
            assert len(app.repository.objects(c,tid,'quality_candidate_root'))==1
            assert len(app.repository.objects(c,tid,'quality_reextraction_action'))==1
            assert app.repository.objects(c,tid,'quality_reextraction_result')[0]['candidate_count']==1
            record=app.delivery.get(c,tid)['measurements'][0]
            assert record['unit']=='m' and record['value']['value']=='0'
            assert app.repository.objects(c,tid,'review_answer')[0]['simulation'] is True
            assert not c.execute("select 1 from jobs where task_id=? and kind='source_reconcile'",(tid,)).fetchone()
    asyncio.run(run())
