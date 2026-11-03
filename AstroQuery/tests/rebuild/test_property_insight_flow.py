"""Normal Scheduler/report transitions; explicitly synthetic model and network."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import RESEARCH_DELIVERY_POLICY
from astroquery_ai.science.property_insights import unpack_materials, PROTOCOL
from tests.rebuild.scenario import application, confirmed_case


@pytest.mark.parametrize('scenario', ['normal','local_repair','failure','pause','cancel','restart'])
def test_normal_m11_property_card_publication_and_recovery(tmp_path, scenario):
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json;calls=[];controls=[];tid=[]
        def knowledge(reference=None):
            manifest={'schema_version':'insight-knowledge/3','release_id':'synthetic-author','content_sha256':'a'*64}
            if reference is None:return {'manifest':manifest}
            with app.repository.read() as c:spec=app.repository.objects(c,tid[0],'confirmed_query')[0]
            b=spec['properties'][0];d=b['definition'];p=b['output_profile'];otype=spec['target']['primary_otype']
            return {'manifest':manifest,'sources':{},'author':{'sources':[],
                'entries':[{'entry_id':'length','title':'合成长度','otypes':[otype],'conditions':['SYNTHETIC method condition'],
                    'blocks':[{'role':'meaning','text':'SYNTHETIC method background; no new measurement.',
                        'basis':'author_knowledge','source_ids':[]}]}],
                'bindings':[{'item_id':'synthetic-item','otype':otype,'property_id':b['property_id'],
                    'definition_ref':{'id':b['property_id'],'version':d['definition_version'],'content_sha256':d['content_sha256']},
                    'output_profile_ref':{'id':p['profile_id'],'version':p['version'],'content_sha256':p['content_sha256']},
                    'applicability_rule_refs':b['rule_refs'],'entry_ids':['length'],'status':'covered','reason':''}]}}
        app.knowledge.load=knowledge
        def setup(scheduler):
            handler=scheduler.handlers['insights']
            async def observe(job):
                tid[:]=[job['task_id']]
                with app.repository.read() as c:
                    pending=app.delivery.get(c,tid[0])
                    assert pending['revision']==1 and pending['report_state']=='pending_insights'
                    assert pending['insight_report']['schema_version']=='InsightReport/4'
                    assert pending['export_schema_version']==2 and pending['task_score']['score'] is None
                if scenario in {'cancel','restart'} and not controls:
                    controls.append(scenario);state=app.repository.get_task(tid[0])
                    if scenario=='cancel':app.repository.control(tid[0],'cancel',str(uuid4()),state['revision'],finalizer=app.delivery.seal)
                    else:
                        app.repository.recover();state=app.repository.get_task(tid[0])
                        assert state['lifecycle']=='interrupted'
                        app.repository.control(tid[0],'continue',str(uuid4()),state['revision'])
                    return
                try:await handler(job)
                except DomainError as exc:
                    if scenario!='pause' or exc.code!='DISPATCH_FORBIDDEN':raise
                    scheduler.fail(job,exc);state=app.repository.get_task(tid[0])
                    assert state['lifecycle']=='paused'
                    app.repository.control(tid[0],'continue',str(uuid4()),state['revision'])
            scheduler.handlers['insights']=observe
        async def respond(**kwargs):
            version=kwargs['profile'].version;body=loads(kwargs['messages'][-1]['content'])
            if version=='shared-verified-literature-names/1':
                label=next(iter(body['verified_names']))
                return {'search_names':[{'source_names':[label],'text':body['verified_names'][label],
                    'basis':'SYNTHETIC exact verified identity'}],'ambiguities':[]},{'attempt_id':'synthetic-shared-name'}
            if version=='feedback-quantity-planning/1':
                return {'direct_expression':'length','quantity_field':'abs','method_expression':None,
                    'intent':'SYNTHETIC length','change_reason':'SYNTHETIC initial','rewrite_useful':False},{'attempt_id':'synthetic-quantity'}
            if version=='metadata-terms-2':
                return {'target_name_labels':[next(iter(body['verified_names']))],'core_terms':['length'],
                    'synonyms':[],'method_terms':[],'intent':'SYNTHETIC','rewrite_useful':False},{'attempt_id':'synthetic-terms'}
            if version=='unified-catalog-quality-2':
                return {'items':[{'item_id':r['item_id'],'subject':'target','quantity_relation':'same',
                    'reported_quantity':'SYNTHETIC whole length','subject_scale':'whole','result_role':'reported_result',
                    'native_representation':'linear','value_match':'exact','unit_match':'exact','errors_match':'not_reported',
                    'evidence_columns':['Length'],'checked_ids':list(body['source_materials'])[:1],
                    'caution_ids':[],'review_issue':None,'reason':'SYNTHETIC source'} for r in body['items']]},{'attempt_id':'synthetic-quality'}
            if kwargs['owner']=='M11':
                assert kwargs['profile'].model=='qwen3.8-max' and version==PROTOCOL
                body=unpack_materials(body);calls.append(kwargs['root_id'])
                if scenario=='failure':raise DomainError('PROVIDER_TIMEOUT','SYNTHETIC technical failure')
                row=body['record_index'][0]
                entry={'text':'本轮结果保留原单位和原文，按实际条件比较。',
                    'measurement_ids':[row['measurement_id']],'evidence_ids':row['evidence_ids'][:1],
                    'claim_ids':[body['knowledge'][0]['claim']['claim_id']]}
                if 'repair_slots' in body:
                    return {'repairs':[{'slot':slot['slot'],'entry':entry} for slot in body['repair_slots']]}, {'attempt_id':'synthetic-repair','model':'qwen3.8-max'}
                if scenario=='pause' and not controls:
                    controls.append('pause');state=app.repository.get_task(tid[0])
                    app.repository.control(tid[0],'pause',str(uuid4()),state['revision'])
                result={'found':[entry],'comparison':[],'uses':[deepcopy(entry)],'limitations':[],'findings':[]}
                if scenario=='local_repair':result['comparison']=[{**entry,'measurement_ids':['M999']}]
                return result,{'attempt_id':'synthetic-property','model':'qwen3.8-max'}
            return await ordinary(**kwargs)
        app.models.json=respond
        state,_=await confirmed_case(app,run_policy=deepcopy(RESEARCH_DELIVERY_POLICY),setup_scheduler=setup)
        assert state['lifecycle']==('cancelled' if scenario=='cancel' else 'completed') and state['science_state']=='sealed'
        assert len(calls)==(0 if scenario=='cancel' else 2 if scenario=='local_repair' else 1)
        with app.repository.read() as c:
            delivery=app.delivery.get(c,state['task_id']);old=app.repository.object(c,state['task_id'],'delivery',delivery['delivery_id'],1)
            assert delivery['snapshot_ref']==old['snapshot_ref'] and delivery['measurements']==old['measurements']
            assert delivery['revision']==2 and delivery['export_schema_version']==2
            report=delivery['insight_report']
            assert report['schema_version']=='InsightReport/4' and len(report['cards'])==1
            assert report['status']==('partial' if scenario in {'failure','cancel'} else 'complete')
            if scenario not in {'failure','cancel'}:
                assert report['cards'][0]['actual_model']=='qwen3.8-max'
                assert report['knowledge_blocks'][0]['conditions']==['SYNTHETIC method condition']
            assert delivery['task_score']['possible_points']==100
            assert not c.execute("select 1 from jobs where task_id=? and status in ('ready','running','waiting_dependency')",(state['task_id'],)).fetchone()
        for fmt in ('json','json_wide','csv_long','csv_wide','package'):
            exported=app.delivery.export(state['task_id'],{'operation_id':str(uuid4()),'task_id':state['task_id'],
                'delivery_id':delivery['delivery_id'],'expected_delivery_revision':2,
                'selection':{'mode':'all','measurement_ids':[]},'format':fmt,'export_schema_version':2})
            assert exported['snapshot_ref']==old['snapshot_ref'] and exported['delivery_revision']==2
    asyncio.run(run())
