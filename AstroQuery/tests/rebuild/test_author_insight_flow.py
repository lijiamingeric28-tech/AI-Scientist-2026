"""Normal production job/state flow with explicit synthetic model responses."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY
from tests.rebuild.scenario import application,confirmed_case,synthetic_author_manifest


@pytest.mark.parametrize('scenario',['normal','failure','pause','cancel','restart'])
def test_normal_new_task_seals_data_then_generates_and_revises_reports(tmp_path,scenario):
 async def run():
    app=application(tmp_path/'data');ordinary=app.models.json;calls=[];controls=[];failure=scenario=='failure'
    manifest=synthetic_author_manifest(app)
    def knowledge(reference=None):
        if reference is None or not tid:return {'manifest':manifest}
        with app.repository.read() as c:
            spec=app.repository.objects(c,tid[0],'confirmed_query')[0]
        b=spec['properties'][0];d=b['definition'];p=b['output_profile'];otype=spec['target']['primary_otype']
        return {'manifest':manifest,'sources':{},'author':{'sources':[],
            'entries':[{'entry_id':'length','title':'合成长度','otypes':[otype],'conditions':[],
                'blocks':[{'role':'meaning','text':'SYNTHETIC length explanation, not a new measurement.',
                    'basis':'author_knowledge','source_ids':[]}]}],
            'bindings':[{'item_id':'synthetic-item','otype':otype,'property_id':b['property_id'],
                'definition_ref':{'id':b['property_id'],'version':d['definition_version'],'content_sha256':d['content_sha256']},
                'output_profile_ref':{'id':p['profile_id'],'version':p['version'],'content_sha256':p['content_sha256']},
                'applicability_rule_refs':b['rule_refs'],'entry_ids':['length'],'status':'covered','reason':''}]}}
    tid=[]
    def setup(scheduler):
        # Observe the task ID after ordinary creation, before it is dispatched.
        handler=scheduler.handlers['insights']
        async def observe(job):
            tid[:]=[job['task_id']]
            with app.repository.read() as c:
                pending=app.delivery.get(c,job['task_id'])
                assert pending['revision']==1 and pending['report_state']=='pending_insights'
                assert pending['task_score']['status']=='pending' and pending['task_score']['score'] is None
                assert app.repository.task(c,job['task_id'])['lifecycle']!='completed'
            if scenario in {'cancel','restart'} and not controls:
                controls.append(scenario)
                state=app.repository.get_task(job['task_id'])
                if scenario=='cancel':
                    app.repository.control(job['task_id'],'cancel',str(uuid4()),state['revision'],finalizer=app.delivery.seal)
                else:
                    app.repository.recover();state=app.repository.get_task(job['task_id'])
                    assert state['lifecycle']=='interrupted'
                    app.repository.control(job['task_id'],'continue',str(uuid4()),state['revision'])
                return
            try:await handler(job)
            except DomainError as exc:
                if scenario!='pause' or exc.code!='DISPATCH_FORBIDDEN':raise
                scheduler.fail(job,exc)
                state=app.repository.get_task(job['task_id'])
                assert state['lifecycle']=='paused'
                app.repository.control(job['task_id'],'continue',str(uuid4()),state['revision'])
        scheduler.handlers['insights']=observe
    app.knowledge.load=knowledge
    async def respond(**kwargs):
        version=kwargs['profile'].version;body=loads(kwargs['messages'][-1]['content'])
        if version=='metadata-terms-2':return {'target_name_labels':[next(iter(body['verified_names']))],
            'core_terms':['length'],'synonyms':[],'method_terms':[],'intent':'SYNTHETIC','rewrite_useful':False},{'attempt_id':'synthetic-metadata'}
        if version=='unified-catalog-quality-2':return {'items':[{'item_id':r['item_id'],'subject':'target','quantity_relation':'same',
            'reported_quantity':'SYNTHETIC whole length','subject_scale':'whole','result_role':'reported_result','native_representation':'linear',
            'value_match':'exact','unit_match':'exact','errors_match':'not_reported','evidence_columns':['Length'],
            'checked_ids':list(body['source_materials'])[:1],'caution_ids':[],'review_issue':None,'reason':'synthetic source'} for r in body['items']]},{'attempt_id':'synthetic-quality'}
        if kwargs['owner']=='M11':
            calls.append(version)
            if failure:raise DomainError('PROVIDER_TIMEOUT','synthetic failure, not science absence')
            if scenario=='pause' and not controls:
                controls.append('pause');state=app.repository.get_task(tid[0])
                app.repository.control(tid[0],'pause',str(uuid4()),state['revision'])
            u=body['units'][0];mid=u['measurements'][0]['measurement_id'];cid=u['claims'][0]['claim']['claim_id']
            return {'units':[{'unit_id':u['unit_id'],'numeric_mode':'snapshot_placeholders/1','paragraphs':[
                {'kind':'source_fact','text':'原报{{V1}}，原单位和原文已保留。','measurement_ids':[],'claim_ids':[]},
                {'kind':'theory_background','text':'该知识段说明量的含义，条件仍需按实际来源理解。','measurement_ids':[],
                    'claim_ids':[cid],'value_assertions':[]}]}]},{'attempt_id':'synthetic-new-generation'}
        return await ordinary(**kwargs)
    app.models.json=respond
    state,_=await confirmed_case(app,run_policy=deepcopy(NORMAL_RUN_POLICY),setup_scheduler=setup)
    assert state['lifecycle']==('cancelled' if scenario=='cancel' else 'completed') and state['science_state']=='sealed'
    assert len(calls)==(0 if scenario=='cancel' else 1)
    with app.repository.read() as c:
        task=state['task_id'];delivery=app.delivery.get(c,task)
        old=app.repository.object(c,task,'delivery',delivery['delivery_id'],1)
        assert old['insight_report']['status']=='pending' and delivery['revision']==2
        assert delivery['snapshot_ref']==old['snapshot_ref'] and delivery['measurements']==old['measurements']
        assert delivery['task_score']['possible_points']==100 and delivery['task_score']['excluded_scope']==[]
        assert delivery['insight_report']['schema_version']=='InsightReport/3'
        assert delivery['insight_report']['status']==('partial' if failure or scenario=='cancel' else 'complete')
        assert delivery['task_score']['components'][-1]['earned']==(0 if failure or scenario=='cancel' else 5)
        assert not c.execute("select 1 from jobs where task_id=? and status in ('ready','running','waiting_dependency')",(task,)).fetchone()
    for fmt in ('json','json_wide','csv_long','csv_wide','package'):
        exported=app.delivery.export(task,{'operation_id':str(uuid4()),'task_id':task,'delivery_id':delivery['delivery_id'],
            'expected_delivery_revision':2,'selection':{'mode':'all','measurement_ids':[]},'format':fmt,'export_schema_version':1})
        assert exported['snapshot_ref']==old['snapshot_ref'] and exported['delivery_revision']==2
    with app.repository.transaction() as c:
        replay=app.delivery.finish_insights(c,task,delivery['insight_report'])
        assert replay['revision']==2
 asyncio.run(run())
