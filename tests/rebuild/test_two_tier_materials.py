"""Synthetic finite-pool/controller tests, not autonomous scientific evidence."""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from copy import deepcopy

from astroquery_ai.runtime.codec import canonical,loads,digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY as NORMAL_RUN_POLICY
from astroquery_ai.runtime.stages import set_stage,advance_stage,current_stage
from astroquery_ai.science.literature import parse_record,FairReadLedger
from astroquery_ai.science.workflow.literature_service import LiteratureService
from astroquery_ai.science.literature_preparation import compile_layer,fetch_layer,prepare,schedule


def document(i,version=1):
    return {'bibcode':f'SYNTHETIC-{i}-v{version}','title':[f'SYNTHETIC work {i}'],
            'doi':[f'10.1234/synthetic{i}'],'doctype':'article','abstract':'SYNTHETIC actual supplied metadata'}


def configuration():
    return {'target':{'main_id':'SYNTHETIC target','aliases':['SYNTHETIC alias']},
        'properties':[{'property_id':'p','definition':{'family_id':'f','name_cn':'合成性质','name_en':'Synthetic quantity',
            'quantity_key':'synthetic.length','description':'Synthetic whole length','value_schema':{'kind':'real'}}}],
        'run_policy':deepcopy(NORMAL_RUN_POLICY)}


def test_program_compiles_the_same_groups_and_escapes_phrases():
    plan={'names':['Object "quoted"','Alias OR data'],'phrases':['quantity (native)','method']}
    for tier in ['abs','full']:
        expression=compile_layer(plan,tier)
        assert expression.startswith('('+tier+':(') and ' AND '+tier+':(' in expression
        assert expression.endswith(') AND doctype:(article OR eprint)')
        assert '\\"quoted\\"' in expression
        assert 'references(' not in expression


def test_bounded_pages_deduplicate_versions_and_exclude_all_previously_evaluated(tmp_path):
    async def run():
        repo=Repository(tmp_path/'db');store=ArtifactStore(tmp_path/'artifacts',repo)
        tid=repo.create_task('SYNTHETIC two-tier paging')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open')
            repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('worker',lease_seconds=600);calls=[];models=[]
        class Steps:
            async def model(self,execution,**kwargs):
                models.append(kwargs);return {'names':['N1'],'phrases':['synthetic quantity'],'intent':'SYNTHETIC'},{'attempt_id':'synthetic'}
            def http(self,execution):return self
            async def request(self,*args,**kwargs):
                params=kwargs['params'];calls.append(params);start=int(params['start'])
                if params['q'].startswith('(abs:'):
                    docs=([document(i,v) for i in range(20) for v in (1,2)] if start==0 else [document(i) for i in range(20,60)])
                    count=80
                else:
                    docs=[document(i) for i in range(start,start+20)];count=60
                return canonical({'response':{'docs':docs,'numFound':count}}),{'status':200}
        service=LiteratureService(SimpleNamespace(repo=repo,app=SimpleNamespace(artifacts=store,
            configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'})),steps=Steps(),extractor=None))
        spec=configuration();binding=spec['properties'][0]
        first=await fetch_layer(service,job,spec,binding,'abs')
        assert len(first['works'])==40 and [p['start'] for p in first['pages']]==[0,40]
        second=await fetch_layer(service,job,spec,binding,'full',first['records'])
        assert len(second['works'])==20 and [p['start'] for p in second['pages']]==[0,20,40]
        assert {r['bibcode'] for r in second['records']}=={document(i)['bibcode'] for i in range(40,60)}
        assert len(models)==1 and len(calls)==5
        await fetch_layer(service,job,spec,binding,'full',first['records'])
        assert len(calls)==5  # Finished tier is recovered, not searched again.
    asyncio.run(run())


def carrier(tmp_path,*,properties=('p',),count=21):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC material controller')['task_id']
    spec=configuration();spec['properties']=[{**spec['properties'][0],'property_id':p} for p in properties]
    spec['spec_hash']=digest(spec)
    works=['w'+str(i) for i in range(count)]
    state={'revision':1,'protocol':'two-tier-materials/1','closed':False,'pools':{
        p:{'property_id':p,'eligible':works.copy(),'evaluated':works.copy(),'attempted':[],
           'decisions':{},'full_used':False,'tiers':['abs']} for p in properties}}
    with repo.transaction() as c:
        repo.mutate_task(c,tid,lifecycle='running',science_state='open');set_stage(repo,c,tid,'acquisition')
        for producer in ('selections','literature_candidates','body_batches','attachment_discovery'):
            repo.producer(c,tid,producer)
        for i,w in enumerate(works):repo.put_object(c,tid,'work',w,1,{'work_id':w,'records':[parse_record(document(i))],'allowed_property_ids':[]})
        repo.put_object(c,tid,'material_preparation',tid,1,state)
        repo.put_object(c,tid,'read_ledger',tid,1,asdict(FairReadLedger(list(properties),{}, {},maximum_works=60*len(properties))))
        repo.enqueue(c,tid,'M04','material_prepare',{'checkpoint':'initial'})
    service=LiteratureService(SimpleNamespace(repo=repo,app=None,steps=None,extractor=None))
    service.spec=lambda c,tid:spec
    return repo,tid,service


def settle_synthetic_downloads(repo,tid,*,fail=()):
    # State-machine input only; this deliberately does not test acquisition.
    while job:=repo.claim_job('synthetic-download',task_id=tid,lease_seconds=600):
        assert job['kind']=='acquire_work';wid=job['payload']['work_id']
        with repo.transaction() as c:
            repo.put_object(c,tid,'acquisition_result',wid,1,{'work_id':wid,'state':'failed' if wid in fail else 'acquired'})
            if wid not in fail:
                work=repo.object(c,tid,'work',wid)
                repo.put_object(c,tid,'prepared_source',wid,1,{'source_id':wid,'work':work,
                    'artifact':{'artifact_id':'synthetic-file-'+wid,'sha256':'synthetic-'+wid},
                    'qualification_ref':{'id':'synthetic-qualification-'+wid}})
                repo.put_object(c,tid,'document_index',wid,1,{'pages':[{'page':1,'text':'SYNTHETIC page'}]})
            repo.finish_job(c,job)


def test_download_backup_then_freeze_once_and_share_file_across_properties(tmp_path):
    async def run():
        repo,tid,service=carrier(tmp_path,properties=('p','q'))
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            assert len(list(c.execute("select 1 from jobs where task_id=? and kind='acquire_work'",(tid,))))==20
            assert not repo.objects(c,tid,'source')
            assert not c.execute("select 1 from jobs where task_id=? and kind in ('paper_batch','attachment_discover')",(tid,)).fetchone()
        settle_synthetic_downloads(repo,tid,fail={'w0'})
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            assert not repo.objects(c,tid,'reading_allocation')
            ready=c.execute("select payload from jobs where task_id=? and kind='acquire_work' and status='ready'",(tid,)).fetchall()
            assert [loads(r[0])['work_id'] for r in ready]==['w20']
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            state=repo.objects(c,tid,'material_preparation')[0]
            assert state['closed'] and not any(p['full_used'] for p in state['pools'].values())
            assert len(state['final_allocations'])==20
            assert all(set(pids)=={'p','q'} for pids in state['final_allocations'].values())
            assert len(repo.objects(c,tid,'source'))==20
            jobs=[dict(r) for r in c.execute('select kind,payload from jobs where task_id=?',(tid,))]
            assert sum(j['kind']=='paper_batch' for j in jobs)==40
            assert sum(j['kind']=='attachment_discover' for j in jobs)==20
            assert all(set(s['work']['allowed_property_ids'])=={'p','q'} for s in repo.objects(c,tid,'source'))
    asyncio.run(run())


def test_open_material_scope_cannot_advance_to_quality_between_subrounds(tmp_path):
    repo,tid,_=carrier(tmp_path,count=0)
    job=repo.claim_job('prepare',task_id=tid)
    with repo.transaction() as c:
        repo.finish_job(c,job)
        repo.enqueue(c,tid,'M07','assess_batch',{'measurement_ids':[]})
        advance_stage(repo,c,tid)
        assert current_stage(c,tid)['stage_id']=='acquisition'
    assert repo.claim_job('quality',task_id=tid) is None


def test_download_loss_uses_full_once_then_closes_finite_shortage(tmp_path,monkeypatch):
    import astroquery_ai.science.literature_preparation as materials
    async def run():
        repo,tid,service=carrier(tmp_path,count=20);searches=[]
        async def layer(execution,job,spec,binding,tier,prior_records):
            searches.append((tier,len(prior_records)))
            work=materials.deduplicate([parse_record(document(99))])[0][0]
            return {'works':[work],'records':work['records'],'tier':'full'}
        async def assess(job,spec,works):
            return {w['work_id']:{'decision':'needs_fulltext','rank':1} for w in works}
        monkeypatch.setattr(materials,'fetch_layer',layer);service.assess_works=assess
        await prepare(service,repo.claim_job('prepare',task_id=tid))
        settle_synthetic_downloads(repo,tid,fail={'w0','w1'})
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid))
        with repo.read() as c:assert not repo.objects(c,tid,'source')
        await prepare(service,repo.claim_job('prepare',task_id=tid))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid))
        with repo.read() as c:
            state=repo.objects(c,tid,'material_preparation')[0]
            pool=state['pools']['p']
            assert state['closed'] and pool['full_used'] and len(pool['acquired'])==19
            assert pool['close_reason']=='bounded_candidate_pool_exhausted'
            assert len(repo.objects(c,tid,'reading_allocation'))==19
        assert searches==[('full',20)]
    asyncio.run(run())


def test_version_bridge_keeps_acquired_id_and_resolves_previous_aliases(tmp_path):
    from astroquery_ai.science.literature_preparation import ingest,resolve_alias
    repo,tid,_=carrier(tmp_path,count=1)
    with repo.transaction() as c:
        repo.put_object(c,tid,'acquisition_result','w0',1,{'work_id':'w0','state':'acquired'})
        # A subsequent version contains the same DOI. It cannot cause another
        # download or leave the material pool pointing at an obsolete ID.
        mapping=ingest(repo,c,tid,[parse_record(document(0,version=2))])
        assert mapping[document(0,version=2)['bibcode']]=='w0'
        aliases=repo.objects(c,tid,'material_aliases')[0]['aliases']
        assert all(resolve_alias(aliases,w)=='w0' for w in aliases)
        assert len(repo.object(c,tid,'work','w0')['records'])==2


def test_terms_repair_distinguishes_target_labels_from_quantity_names(tmp_path):
    from astroquery_ai.science.literature_preparation import term_plan
    async def run():
        repo,tid,service=carrier(tmp_path,count=0);job=repo.claim_job('terms',task_id=tid)
        calls=[]
        class Steps:
            async def model(self,execution,**kw):
                body=loads(kw['messages'][0]['content']);calls.append((body,kw))
                if len(calls)==1:
                    return {'names':['synthetic quantity'],'phrases':['quantity'],'intent':'wrong role'},{'attempt_id':'first'}
                assert body['feedback']['invalid_target_names']==['synthetic quantity']
                assert body['target']['main_id']=='SYNTHETIC target'
                return {'target_name_labels':['N1'],'quantity_phrases':['ordinary method'],'intent':'correct roles'},{'attempt_id':'second'}
        service.steps=Steps();spec=configuration()
        result=await term_plan(service,job,spec,spec['properties'][0])
        assert result['names']==['SYNTHETIC target'] and result['phrases']==['ordinary method']
        assert len(calls)==2 and len({kw['root_id'] for _,kw in calls})==1
    asyncio.run(run())


def test_two_layer_assessments_have_independent_immutable_records_and_recover_without_repaying(tmp_path):
    async def run():
        repo,tid,service=carrier(tmp_path,count=0);job=repo.claim_job('layers',task_id=tid)
        calls=[]
        class Steps:
            async def model(self,execution,**kw):
                calls.append(kw)
                return {'works':[{'id':'W1','decision':'needs_fulltext','properties':['P1'],
                    'evidence':[],'rank':1,'reason':'SYNTHETIC supplied body needed'}]},{'attempt_id':'actual-synthetic-'+str(len(calls))}
        service.steps=Steps();spec=configuration()
        first=[{'work_id':'synthetic-abs','records':[parse_record(document(1))],'retrieval_tier':'abs'}]
        second=[{'work_id':'synthetic-full','records':[parse_record(document(2))],'retrieval_tier':'full'}]
        assert (await service.assess_works(job,spec,first))['synthetic-abs']['decision']=='needs_fulltext'
        assert (await service.assess_works(job,spec,second))['synthetic-full']['decision']=='needs_fulltext'
        await service.assess_works(job,spec,first)
        await service.assess_works(job,spec,second)
        with repo.read() as c:
            assert len(repo.objects(c,tid,'literature_candidate_evaluation'))==2
            assert len(repo.objects(c,tid,'literature_assessment'))==2
        assert len(calls)==2 and len({kw['root_id'] for kw in calls})==2
    asyncio.run(run())
