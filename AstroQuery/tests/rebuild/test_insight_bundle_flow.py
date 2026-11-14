"""Normal Scheduler/report transitions; explicitly synthetic model and network."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import RESEARCH_DELIVERY_POLICY
from astroquery_ai.science.property_insights import unpack_materials, PROTOCOL
from tests.rebuild.scenario import application, confirmed_case, synthetic_author_manifest


@pytest.mark.parametrize('scenario', ['normal','failure','material_failure','pause','cancel','restart','unqualified','material_io','no_knowledge','tampered_context','budget','findings'])
def test_bundle_real_publication_and_recovery(tmp_path, scenario, monkeypatch):
    async def run():
        app=application(tmp_path/'data');ordinary=app.models.json;calls=[];controls=[];tid=[];capture_specs=[];material_calls=[]
        manifest=synthetic_author_manifest(app)
        def knowledge(reference=None):
            if reference is None or (not capture_specs and not tid):return {'manifest':manifest}
            if capture_specs:spec=capture_specs[-1]
            else:
                with app.repository.read() as c:spec=app.repository.objects(c,tid[0],'confirmed_query')[0]
            if scenario=='no_knowledge':raise DomainError('KB_MISSING','synthetic missing release')
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
        from astroquery_ai.science import task_knowledge
        capture = task_knowledge.capture
        def pin_capture(application, spec):
            capture_specs.append(spec)
            return capture(application, spec)
        monkeypatch.setattr(task_knowledge, 'capture', pin_capture)
        from astroquery_ai.science import property_insight_generation
        async def forbidden_recheck(*args,**kwargs):raise AssertionError('new bundle must not run automatic owner rechecks')
        monkeypatch.setattr(property_insight_generation,'recheck',forbidden_recheck)
        def setup(scheduler):
            handler=scheduler.handlers['insights']
            async def observe(job):
                tid[:]=[job['task_id']]
                with app.repository.read() as c:
                    pending=app.delivery.get(c,tid[0])
                    assert pending['revision']==1 and pending['report_state']=='pending_insights'
                    assert pending['insight_report']['schema_version']=='InsightBundle/1'
                    assert pending['insight_report']['knowledge_context_ref']
                if scenario=='normal':
                    from astroquery_ai.science import insight_bundle
                    with app.repository.read() as c:
                        query_ref=loads(app.repository.task(c,tid[0])['query_ref'])
                        frozen=app.repository.object(c,tid[0],'confirmed_query',query_ref['id'],query_ref['version'])
                    children=deepcopy(pending['insight_report'])
                    children['material_report']['status']='generated'
                    children['property_report']['status']='complete'
                    proposed=insight_bundle.compose(pending,frozen,children['material_report'],children['property_report'])
                    for branch in ('material_report','property_report'):
                        for field,value in (('id','other'),('version',2),('content_sha256','other')):
                            wrong=deepcopy(proposed);wrong[branch]['knowledge_context_ref'][field]=value
                            with pytest.raises(DomainError) as failed:
                                with app.repository.transaction() as c:app.delivery.finish_insights(c,tid[0],wrong)
                            assert failed.value.code=='TASK_KNOWLEDGE_HASH'
                    with app.repository.read() as c:assert app.delivery.get(c,tid[0])['revision']==1
                if scenario=='tampered_context':
                    with app.repository.transaction() as c:
                        c.execute("UPDATE objects SET payload=? WHERE task_id=? AND kind='task_knowledge'", (b'{}',tid[0]))
                app.knowledge.load=lambda *args: (_ for _ in ()).throw(AssertionError('current formal knowledge accessed'))
                from astroquery_ai.science.theory_knowledge import TheoryKnowledgeStore
                monkeypatch.setattr(TheoryKnowledgeStore,'get_instance',lambda: (_ for _ in ()).throw(AssertionError('current theory knowledge accessed')))
                def forbidden(*args,**kwargs):raise AssertionError('current user knowledge accessed')
                monkeypatch.setattr(app.user_knowledge,'search',forbidden)
                with app.repository.read() as c:
                    assert pending['export_schema_version']==2 and pending['task_score']['score'] is None
                if scenario in {'cancel','restart'} and not controls:
                    controls.append(scenario);state=app.repository.get_task(tid[0])
                    if scenario=='cancel':app.repository.control(tid[0],'cancel',str(uuid4()),state['revision'],finalizer=app.delivery.seal)
                    else:
                        app.repository.recover();state=app.repository.get_task(tid[0])
                        assert state['lifecycle']=='interrupted'
                        app.repository.control(tid[0],'continue',str(uuid4()),state['revision'])
                    return
                try:
                    await handler(job)
                    if scenario=='normal':
                        before=(list(calls),list(material_calls))
                        await handler(job)
                        assert before==(calls,material_calls)
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
            if kwargs.get('purpose')=='material_summary':
                from astroquery_ai.science.material_summaries import BUNDLE_KNOWLEDGE_RULE
                assert BUNDLE_KNOWLEDGE_RULE in kwargs['messages'][0]['content']
                assert body['knowledge_context_ref']==capture_specs[-1]['knowledge_context_ref']
                assert body['knowledge_policy']['role']=='background_not_source_facts'
                for field in body['properties']:
                    for background in field['knowledge_background']:
                        assert background['conditions']==['SYNTHETIC method condition']
                        assert background['applicability_state']=='conditional'
                        assert background['origin']=='formal_release' and background['claim_id']
                material_calls.append(kwargs['root_id'])
                if scenario=='material_io':raise OSError('synthetic material storage read failure')
                if scenario=='budget':raise DomainError('BUDGET_EXHAUSTED','synthetic exhausted budget')
                if scenario=='material_failure':raise DomainError('PROVIDER_TIMEOUT','synthetic material timeout')
                return {r['label']:'该资料保留完整来源内容和已有测量，条件需依照原文解释。' for r in body['properties']}, {'attempt_id':'synthetic-material','model':'qwen3.8-flash'}
            if kwargs['owner']=='M11':
                assert kwargs['profile'].model=='qwen3.8-max' and version==PROTOCOL
                body=unpack_materials(body);calls.append(kwargs['root_id'])
                if scenario in {'failure','unqualified'}:raise DomainError('PROFILE_NOT_VALIDATED' if scenario=='unqualified' else 'PROVIDER_TIMEOUT','SYNTHETIC technical failure')
                row=body['record_index'][0]
                entry={'text':'本轮结果保留原单位和原文，按实际条件比较。',
                    'measurement_ids':[row['measurement_id']],'evidence_ids':row['evidence_ids'][:1],
                    'claim_ids':[body['knowledge'][0]['claim']['claim_id']] if body['knowledge'] else []}
                if 'repair_slots' in body:
                    return {'repairs':[{'slot':slot['slot'],'entry':entry} for slot in body['repair_slots']]}, {'attempt_id':'synthetic-repair','model':'qwen3.8-max'}
                if scenario=='pause' and not controls:
                    controls.append('pause');state=app.repository.get_task(tid[0])
                    app.repository.control(tid[0],'pause',str(uuid4()),state['revision'])
                result={'found':[entry],'comparison':[],'uses':[deepcopy(entry)],'limitations':[],'findings':[]}
                if scenario=='findings':
                    result['findings']=[{'classification':'explicit_counterevidence','issue':'subject',
                        'measurement_ids':entry['measurement_ids'],'evidence_ids':entry['evidence_ids'],
                        'reason':'该来源对象角色仍需人工核对，保留已冻结原始记录。'}]
                if scenario=='local_repair':result['comparison']=[{**entry,'measurement_ids':['M999']}]
                return result,{'attempt_id':'synthetic-property','model':'qwen3.8-max'}
            return await ordinary(**kwargs)
        app.models.json=respond
        policy=deepcopy(RESEARCH_DELIVERY_POLICY)
        policy['insights']['presentation']='research-workbench/2'
        state,_=await confirmed_case(app,run_policy=policy,setup_scheduler=setup)
        assert state['lifecycle']==('cancelled' if scenario=='cancel' else 'completed') and state['science_state']=='sealed'
        assert len(calls)==(0 if scenario in {'cancel','tampered_context'} else 2 if scenario=='local_repair' else 1)
        if scenario in {'normal','failure','pause','restart','unqualified','no_knowledge','findings'}:
            assert len(material_calls)==1
        with app.repository.read() as c:
            delivery=app.delivery.get(c,state['task_id']);old=app.repository.object(c,state['task_id'],'delivery',delivery['delivery_id'],1)
            assert delivery['snapshot_ref']==old['snapshot_ref'] and delivery['measurements']==old['measurements']
            assert delivery['revision']==2 and delivery['export_schema_version']==2
            bundle=delivery['insight_report']
            assert bundle['schema_version']=='InsightBundle/1'
            assert bundle['delivery_revision']==delivery['revision']==2
            assert bundle['generation_delivery_revision']==old['revision']==1
            assert bundle['material_report']['status']==('partial' if scenario in {'cancel','material_failure','material_io','tampered_context','budget'} else 'generated')
            assert bundle['status']==('partial' if scenario in {'failure','material_failure','material_io','cancel','unqualified','tampered_context','budget','no_knowledge'} else 'complete')
            if scenario in {'failure','unqualified'}:
                assert bundle['components']['property']['reason']==('PROFILE_NOT_VALIDATED' if scenario=='unqualified' else 'PROVIDER_TIMEOUT')
            if scenario in {'material_failure','budget'}:
                assert bundle['components']['material']['reason']==('BUDGET_EXHAUSTED' if scenario=='budget' else 'PROVIDER_TIMEOUT')
            assert bundle['knowledge_context_ref']==old['insight_report']['knowledge_context_ref']
            assert delivery.get('dispositions')==old.get('dispositions')
            report=bundle['property_report']
            assert report['schema_version']=='InsightReport/4' and len(report['cards'])==1
            assert report['status']==('partial' if scenario in {'failure','cancel','unqualified','tampered_context','no_knowledge'} else 'complete')
            if scenario not in {'failure','cancel','unqualified','tampered_context'}:
                assert report['cards'][0]['actual_model']=='qwen3.8-max'
                if scenario!='no_knowledge':assert report['knowledge_blocks'][0]['conditions']==['SYNTHETIC method condition']
            if scenario=='findings':
                assert report['cards'][0]['findings'][0]['owner_state']=='pending_review'
                assert not report['owner_rechecks']
            if scenario=='tampered_context':
                assert not material_calls and not calls
                assert bundle['components']['property']['reason']=='TASK_KNOWLEDGE_HASH'
            assert delivery['task_score']['possible_points']==100
            assert not c.execute("select 1 from jobs where task_id=? and status in ('ready','running','waiting_dependency')",(state['task_id'],)).fetchone()
        for fmt in ('json','json_wide','csv_long','csv_wide','package'):
            exported=app.delivery.export(state['task_id'],{'operation_id':str(uuid4()),'task_id':state['task_id'],
                'delivery_id':delivery['delivery_id'],'expected_delivery_revision':2,
                'selection':{'mode':'all','measurement_ids':[]},'format':fmt,'export_schema_version':2})
            assert exported['snapshot_ref']==old['snapshot_ref'] and exported['delivery_revision']==2
    asyncio.run(run())

