"""Bounded synthetic transport/state tests; not the ten real-query results."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pymupdf
import pytest

from astroquery_ai.runtime.codec import canonical, loads, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.run_policy import FEEDBACK_RUN_POLICY, NORMAL_RUN_POLICY, request_policy, literature_strategy
from astroquery_ai.science.feedback_retrieval import (check_name_row, compile_concepts, query_key,
    choose_next_search, fetch_page, record_round, long_downloads, text_windows)
from astroquery_ai.science.workflow.literature_service import LiteratureService
from tests.rebuild.test_two_tier_materials import configuration, document, carrier, settle_synthetic_downloads


def test_published_default_keeps_explicit_old_and_frozen_candidate_policies():
    before = deepcopy(NORMAL_RUN_POLICY)
    assert request_policy(SimpleNamespace(runtime={'retrieval_policy_version':'retrieval-release/1'})) == before
    p = request_policy(SimpleNamespace(runtime={'retrieval_policy_version':'retrieval-feedback/1'}))
    assert request_policy(SimpleNamespace(runtime={})) == p
    assert p['literature']['maximum_search_pages']==8
    assert p['literature']['execution_mode']=='normal-query/1'
    assert p['documents']['manuscript_contract']=='identity-and-body/1'
    assert literature_strategy({'run_policy':p})['D']=='D1'
    with pytest.raises(DomainError):
        literature_strategy({'run_policy':{**p,'literature':{**p['literature'],'stop_after_materials':True}}})
    assert 'manuscript_contract' not in FEEDBACK_RUN_POLICY['documents']
    p['literature']['maximum_search_pages']=1
    assert NORMAL_RUN_POLICY==before and FEEDBACK_RUN_POLICY['literature']['maximum_search_pages']==8


def test_bad_entry_shape_has_specific_repair_diagnostic_and_keeps_candidate_scope():
    from astroquery_ai.query.semantic_selection import checked_selection
    raw={'property_operation':'replace','requests':[{'text':'synthetic quantity','coverage':'complete','gap':'',
          'candidate_property_ids':['p'],'equivalent_property_ids':['p'],'explanation':'actual supplied definition'}],
          'conditions':[],'unknown_fragments':[]}
    with pytest.raises(DomainError) as error:
        checked_selection(raw,'synthetic quantity',[{'property_id':'p'}])
    assert error.value.details['missing_fields']==['clarification_needed']
    raw['clarification_needed']=False
    result,repairs=checked_selection(raw,'synthetic quantity',[{'property_id':'p'}])
    assert result['requests'][0]['candidates'][0]['property_id']=='p'
    with pytest.raises(DomainError):
        checked_selection(raw,'synthetic quantity',[{'property_id':'other'}])


@pytest.mark.parametrize('source,good,bad',[
    ('HD 12345 b','HD12345b','HD12345'),
    ('HD 12345 b','HD12345b','HD12345B'),
    ('J0123−4567','J0123-4567','J0123+4567'),
    ('Synthetic B','Synthetic B','Synthetic A'),
    ('Synthetic B','SyntheticB','SyntheticA'),
])
def test_mechanical_name_identity_parts(source,good,bad):
    row={'source_names':['N1'],'text':good,'basis':'ordinary typesetting of the actual identifier'}
    assert check_name_row(row,{'N1':source})['text']==good
    with pytest.raises(DomainError):
        check_name_row({**row,'text':bad},{'N1':source})


def test_boolean_scope_body_only_quantity_and_cosmetic_rewrite_identity():
    a=compile_concepts(['SYNTHETIC 10 b'],'"quantity" OR "method"',quantity_field='body')
    b=compile_concepts(['SYNTHETIC 10 b'],'method OR quantity',quantity_field='body')
    assert '=abs:("SYNTHETIC 10 b") AND body:' in a and 'full:' not in a
    assert query_key(a)==query_key(b)
    with pytest.raises(DomainError):
        compile_concepts(['SYNTHETIC 10 b'],'full:quantity',quantity_field='body')


def test_no_single_duplicate_page_exhaustion_and_reserve_body_opportunity():
    p=FEEDBACK_RUN_POLICY['literature']
    search={'quantity_field':'abs','next_page':2,'closed_reason':None,'no_candidate_pages':1,'page_attempts':{'0':1,'1':1}}
    assert choose_next_search({'searches':[search]},p)==('continue',None)
    search['no_candidate_pages']=2
    assert choose_next_search({'searches':[search]},p)[0]=='new'
    a={**search,'next_page':4,'page_attempts':{str(i):1 for i in range(4)}}
    b={**search,'next_page':3,'no_candidate_pages':0,'page_attempts':{str(i):1 for i in range(3)}}
    assert choose_next_search({'searches':[a,b]},p)==('new','body')
    b['page_attempts']['3']=1
    assert choose_next_search({'searches':[a,b]},p)==('stop','trial_page_boundary')


def test_ads_exclusions_preserve_direction_literals_and_positive_evidence_windows():
    expr='(size OR "physical size") AND NOT ("Q_*" OR proxy)'
    query=compile_concepts(['Synthetic 1 b'],expr)
    assert r'"Q_\*"' in query
    assert query_key(query)==query_key(compile_concepts(['Synthetic 1 b'],expr.replace('AND NOT','NOT')))
    assert query_key(query)!=query_key(compile_concepts(['Synthetic 1 b'],'("Q_*" OR proxy) NOT ("physical size" OR size)'))
    windows=text_windows({'pages':[{'page':1,'text':'Only proxy appears.'},{'page':2,'text':'Physical size measured.'}]},
                         {'direct_expression':expr})
    assert {w['page'] for w in windows}=={2}
    with pytest.raises(DomainError):
        compile_concepts(['Synthetic 1 b'],'size OR references(test)')


def test_malformed_quantity_is_local_across_initial_search_and_refill(tmp_path):
    from astroquery_ai.science.metadata_preparation import discover
    async def run():
        repo=Repository(tmp_path/'db')
        tid=repo.create_task('SYNTHETIC mixed property plans')['task_id']
        spec=configuration()
        spec['run_policy']=deepcopy(FEEDBACK_RUN_POLICY)
        spec['target']['target_id']='synthetic-target'
        spec['properties']=[{**spec['properties'][0],'property_id':key,
            'definition':{**spec['properties'][0]['definition'],'name_en':label}}
            for key,label in [('a','safe fallback'),('b','normal quantity'),('c','')]]
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open')
            repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('worker',task_id=tid,lease_seconds=60)
        calls=[]
        class Steps:
            async def model(self,execution,**kw):
                body=loads(kw['messages'][0]['content'])
                if 'verified_names' in body:
                    return {'search_names':[{'text':'SYNTHETIC target','source_names':['N1'],'basis':'given name'}]}, {'attempt_id':'names'}
                name=body['quantity']['base_quantity']['name_en']
                expr='"test quantity"' if name=='normal quantity' else 'NOT "exclusion only"'
                return {'direct_expression':expr,'quantity_field':'abs'},{'attempt_id':name+'-terms'}
            def http(self,execution):return self
            async def request(self,*args,**kwargs):
                await asyncio.sleep(0)
                calls.append(kwargs['params']['q'])
                return canonical({'response':{'docs':[document(1)],'numFound':1}}),{'status':200}
        service=LiteratureService(SimpleNamespace(repo=repo,steps=Steps(),extractor=None,
            app=SimpleNamespace(artifacts=ArtifactStore(tmp_path/'artifacts',repo),
                                configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))))
        service.spec=lambda c,task_id:spec
        async def assess(job,spec,works):
            return {w['work_id']:{'decision':'relevant','rank':1} for w in works}
        service.assess_works=assess
        await discover(service,job,spec)
        with repo.read() as c:
            pools=repo.objects(c,tid,'material_preparation')[0]['pools']
            assert pools['a']['eligible'] and pools['b']['eligible'] and not pools['c']['eligible']
            assert len(calls)==2 and any('"safe fallback"' in q for q in calls)
            states={s['property_id']:s for s in repo.objects(c,tid,'literature_feedback_state')}
            assert states['c']['closed_reason']=='quantity_plan_invalid'
            assert c.execute("select status from jobs where job_id=?",(job['job_id'],)).fetchone()[0]=='succeeded'
        # Refill the fallback property. Its old abstract query is available
        # for one body-side search even if the new model expression is invalid.
        refill=repo.claim_job('next',task_id=tid,lease_seconds=60)
        page=await fetch_page(service,refill,spec,spec['properties'][0],2)
        assert page['quantity_field']=='body' and 'body:("safe fallback")' in page['query']
    asyncio.run(run())


def test_page_is_evaluated_before_next_page_and_restart_reuses_completed_layer(tmp_path):
    async def run():
        repo=Repository(tmp_path/'db'); store=ArtifactStore(tmp_path/'artifacts',repo)
        tid=repo.create_task('SYNTHETIC feedback paging')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open')
            repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('paging',task_id=tid,lease_seconds=600)
        s=configuration();s['run_policy']=deepcopy(FEEDBACK_RUN_POLICY);s['target']['target_id']='synthetic-target'
        calls=[];models=[]
        class Steps:
            async def model(self,execution,**kw):
                body=loads(kw['messages'][0]['content']);models.append(body)
                if 'verified_names' in body:
                    return {'search_names':[{'text':'SYNTHETIC target','source_names':['N1'],'basis':'actual supplied identity'}]},{'attempt_id':'names'}
                return {'direct_expression':'"synthetic quantity"','quantity_field':'abs','intent':'SYNTHETIC'}, {'attempt_id':'terms'}
            def http(self,execution):return self
            async def request(self,*args,**kw):
                start=int(kw['params']['start']);calls.append(start)
                # First page contains two versions for each of twenty works.
                docs=[document(i,v) for i in range(20) for v in (1,2)] if start==0 else [document(i) for i in range(20,60)]
                return canonical({'response':{'docs':docs,'numFound':200}}),{'status':200}
        svc=LiteratureService(SimpleNamespace(repo=repo,steps=Steps(),extractor=None,
            app=SimpleNamespace(artifacts=store,configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))))
        first=await fetch_page(svc,job,s,s['properties'][0],1)
        assert calls==[0] and len(first['works'])==20
        decisions={w['work_id']:{'decision':'needs_fulltext'} for w in first['works']}
        record_round(svc,job,first,decisions)
        record_round(svc,job,first,decisions)  # Same page on recovery is not two empty pages.
        recovered=await fetch_page(svc,job,s,s['properties'][0],1)
        assert recovered==first and calls==[0]
        second=await fetch_page(svc,job,s,s['properties'][0],2,first['records'],{'D':2,'L':1,'F':3})
        assert calls==[0,40] and len(second['works'])==40
        assert len(models)==2  # shared names once, quantity once, no blind rewrite.
        with repo.read() as c:
            fs=repo.objects(c,tid,'literature_feedback_state')[0]
            assert fs['searches'][0]['pages'][0]['eligible_new']==20
    asyncio.run(run())


def test_F_never_substitutes_for_D_and_long_versions_do_not_double_count():
    pool={'attempted':['a','b','c','d']}
    results={'a':{'state':'skipped','skipped_versions':[{'verified_long_download':True}]*2},
             'b':{'state':'skipped','skipped_versions':[{'verified_long_download':False}]},
             'c':{'state':'acquired','skipped_versions':[{'verified_long_download':True}]},
             'd':{'state':'failed'}}
    assert long_downloads(pool,results)==['a']


def test_actual_long_bytes_identity_and_pages_are_counted_separately(tmp_path):
    from tests.rebuild.test_literature_lab_downloads import carrier as download_carrier
    from astroquery_ai.science.workflow.paper_service import PaperService
    from astroquery_ai.science.workflow.context import ScienceContext
    async def run():
        app,tid,work,_=download_carrier(tmp_path)
        p=deepcopy(FEEDBACK_RUN_POLICY);p['literature']['stop_after_materials']=True
        with app.repository.transaction() as c:
            spec=app.repository.objects(c,tid,'confirmed_query')[0];spec.update(run_policy=p)
            spec['spec_hash']=digest({k:v for k,v in spec.items() if k!='spec_hash'})
            ref=app.repository.put_object(c,tid,'confirmed_query','spec',2,spec)
            app.repository.mutate_task(c,tid,query_ref=canonical(ref).decode())
            work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/long.pdf'}]
            app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        with pymupdf.open() as doc:
            for i in range(51):
                page=doc.new_page();page.insert_text((30,40),'A synthetic real acquisition title\nDOI: 10.1234/synthetic-lab\nSYNTHETIC complete page '+str(i+1))
            pdf=doc.tobytes()
        def transport(req):
            if '/resolver/' in str(req.url):return httpx.Response(200,json={'links':{'records':[]}})
            return httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(transport)
        svc=PaperService(ScienceContext(app))
        await svc.acquire_work(app.repository.claim_job('long',task_id=tid,lease_seconds=600))
        with app.repository.read() as c:
            result=app.repository.objects(c,tid,'acquisition_result')[0]
            assert result['state']=='skipped'
            assert result['skipped_versions'][0]['verified_long_download'] is True
            assert result['skipped_versions'][0]['page_count']==51
            assert app.repository.objects(c,tid,'long_document_index')[0]['page_count']==51
            assert not app.repository.objects(c,tid,'prepared_source')
            assert not c.execute("select 1 from jobs where task_id=? and kind in ('paper_batch','attachment_discover')",(tid,)).fetchone()
        artifact=result['skipped_versions'][0]['artifact']['artifact_id']
        with pytest.raises(DomainError) as gate:
            await app.parse_owned(tid,artifact,'page_image',page=1)
        assert gate.value.code=='PDF_PHYSICAL_PAGE_LIMIT'
    asyncio.run(run())


def test_download_failure_backups_same_task_shared_file_and_no_downstream(tmp_path):
    from astroquery_ai.science.literature_preparation import prepare,schedule
    async def run():
        repo,tid,svc=carrier(tmp_path,properties=('p','q'))
        spec=svc.spec(None,tid);spec['run_policy']=deepcopy(FEEDBACK_RUN_POLICY)
        spec['run_policy']['literature']['stop_after_materials']=True
        with repo.transaction() as c:
            state=repo.objects(c,tid,'material_preparation')[0];state.update(protocol='metadata-materials/1',revision=2)
            for pool in state['pools'].values():pool.update(batches_used=1)
            repo.put_object(c,tid,'material_preparation',tid,2,state)
        await prepare(svc,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid,fail={'w0'})
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('refill',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('finish',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            state=repo.objects(c,tid,'material_preparation')[0]
            assert state['closed'] and len(state['final_allocations'])==20
            assert all(set(v)=={'p','q'} for v in state['final_allocations'].values())
            assert all(p['download_counts']=={'D':20,'L':0,'F':20} for p in state['pools'].values())
            assert not c.execute("select 1 from jobs where task_id=? and kind in ('paper_batch','attachment_discover')",(tid,)).fetchone()
    asyncio.run(run())


def test_local_reuse_navigation_is_exact_page_text_not_a_measurement():
    index={'pages':[{'page':1,'text':'Other data'}, {'page':2,'text':'Before\nsynthetic quantity +/- uncertainty\nAfter'}]}
    windows=text_windows(index,{'direct_expression':'"synthetic quantity"'})
    assert len(windows)==1 and windows[0]['page']==2
    w=windows[0]
    assert w['text']==index['pages'][1]['text'][w['start']:w['end']]
    assert 'measurement' not in w


def test_local_reuse_requires_own_page_evidence_and_does_not_redownload(tmp_path):
    from astroquery_ai.science.feedback_retrieval import reuse_downloads
    from astroquery_ai.science.literature_preparation import prepare
    async def run():
        repo,tid,svc=carrier(tmp_path,properties=('p','q'),count=2)
        spec=svc.spec(None,tid);spec['target']['target_id']='synthetic-target'
        spec['run_policy']=deepcopy(FEEDBACK_RUN_POLICY)
        with repo.transaction() as c:
            state=repo.objects(c,tid,'material_preparation')[0];state['revision']=2
            state['pools']['q']['eligible']=[]
            repo.put_object(c,tid,'material_preparation',tid,2,state)
        await prepare(svc,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:
            for source in repo.objects(c,tid,'prepared_source'):
                source['title']=['SYNTHETIC title']
                repo.put_object(c,tid,'prepared_source',source['source_id'],2,source)
                repo.put_object(c,tid,'document_index',source['source_id'],2,
                    {'pages':[{'page':1,'text':'SYNTHETIC target synthetic quantity is adopted here.'}]})
            repo.put_object(c,tid,'literature_term_plan','test-plan',1,
                {'property_id':'q','direct_expression':'"synthetic quantity"'})
            repo.enqueue(c,tid,'M04','material_prepare',{'checkpoint':'local-test'})
        calls=[]
        class Steps:
            async def model(self,execution,**kwargs):
                calls.append(kwargs)
                return {'works':[{'id':'W1','status':'supported','evidence':['E1'],'role':'adopted','reason':'actual same-object quantity'},
                                 {'id':'W2','status':'supported','evidence':['E1'],'role':'adopted','reason':'invalid other-work evidence'}]}, {'attempt_id':'synthetic-local'}
        svc.steps=Steps()
        state['pools']['q']['acquired']=[]
        job=repo.claim_job('local',task_id=tid,lease_seconds=600)
        assert await reuse_downloads(svc,job,spec,state,[spec['properties'][1]])
        assert state['pools']['q']['eligible']==['w0']
        with repo.read() as c:
            checks=repo.objects(c,tid,'material_compatibility')
            assert [x['status'] for x in checks].count('supported')==1
            assert not repo.objects(c,tid,'measurement')
        assert len(calls)==1
    asyncio.run(run())


def test_new_real_same_work_link_can_recover_once_without_resetting_url_budget(tmp_path):
    from astroquery_ai.science.papers.download_support import source_options_hash
    from astroquery_ai.science.literature_preparation import prepare,schedule
    async def run():
        repo,tid,svc=carrier(tmp_path,count=1)
        spec=svc.spec(None,tid);spec['run_policy']=deepcopy(FEEDBACK_RUN_POLICY)
        with repo.transaction() as c:
            st=repo.objects(c,tid,'material_preparation')[0];st.update(protocol='metadata-materials/1',revision=2)
            st['pools']['p'].update(batches_used=1)
            repo.put_object(c,tid,'material_preparation',tid,2,st)
        await prepare(svc,repo.claim_job('first',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid,fail={'w0'})
        with repo.transaction() as c:
            work=repo.object(c,tid,'work','w0');before=source_options_hash(work)
            repo.put_object(c,tid,'acquisition_result','w0',2,
                {'work_id':'w0','state':'failed','source_options_hash':before,'recovery_round':0})
            work['records'][0]['raw']['links_data']=[{'link_type':'AUTHOR_PDF','url':'https://publisher.example/new.pdf'}]
            repo.put_object(c,tid,'work','w0',2,work);schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('new-link',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            ready=[loads(x[0]) for x in c.execute("select payload from jobs where task_id=? and kind='acquire_work' and status='ready'",(tid,))]
            assert len(ready)==1 and ready[0]['acquisition_recovery_round']==1
            assert len(repo.objects(c,tid,'read_ledger')[0]['selections'])==1
        modified=deepcopy(work);modified['records'][0]['abstract']='Only metadata wording changed'
        assert source_options_hash(modified)==source_options_hash(work)
    asyncio.run(run())


def test_same_task_local_grant_does_not_use_an_external_page_candidate_slot(tmp_path):
    from astroquery_ai.science.metadata_preparation import merge_batches
    repo,tid,svc=carrier(tmp_path,count=2)
    svc.spec(None,tid)['run_policy']=deepcopy(FEEDBACK_RUN_POLICY)
    svc.spec(None,tid)['run_policy']['literature']['maximum_candidates']=1
    with repo.transaction() as c:
        state=repo.objects(c,tid,'material_preparation')[0]
        state['pools']['p'].update(compatibility_grants=['w1'],batches_used=1)
        batch=[(svc.spec(None,tid)['properties'][0],{'records':[],'works':[],'tier':'synthetic-empty-page'}, {})]
        merge_batches(svc,c,tid,state,batch)
        assert len(state['pools']['p']['evaluated'])==2
        state['pools']['p']['evaluated'].append('unexpected-third-external-work')
        with pytest.raises(DomainError):merge_batches(svc,c,tid,state,batch)


def test_local_reuse_initial_batches_fit_without_cutting_page_evidence(tmp_path):
    from astroquery_ai.science.feedback_retrieval import reuse_batches,reuse_messages,apply_local_grant
    from astroquery_ai.runtime.calls import input_upper_bound
    repo,tid,svc=carrier(tmp_path,count=1)
    spec=svc.spec(None,tid);binding=spec['properties'][0]
    docs=[{'id':'W'+str(i),'abstracts':['duplicated abstract '*200]*3,
           'actual_local_windows':[{'id':'E'+str(i),'page':1,'text':'original page uncertainty '*360}]} for i in range(4)]
    batches=reuse_batches(spec,binding,docs,maximum=24000)
    assert len(batches)>1
    assert all(input_upper_bound(reuse_messages(spec,binding,b))<=24000 for b in batches)
    assert [x['actual_local_windows'] for b in batches for x in b]==[x['actual_local_windows'] for x in docs]
    assert all(len(x['abstracts'])==1 for b in batches for x in b)
    pool={'eligible':[],'evaluated':[],'acquired':[],'decisions':{}}
    saved={'id':'saved','status':'supported','reason':'actual evidence already checked'}
    assert apply_local_grant(pool,'p','w',saved)
    assert not apply_local_grant(pool,'p','w',saved)
    assert pool['compatibility_grants']==['w']


def test_one_bad_name_does_not_discard_other_verified_names():
    from astroquery_ai.science.feedback_retrieval import checked_name_rows
    names={'N1':'SYN  1234','N2':'CAT 084-03 1'}
    valid,rejected=checked_name_rows([
        {'text':'SYN 1234','source_names':['N1'],'basis':'actual supplied N1'},
        {'text':'CAT 84-3.1','source_names':['N2'],'basis':'unverified change of numbered identifier'}],names)
    assert [x['text'] for x in valid]==['SYN 1234']
    assert len(rejected)==1 and rejected[0]['reason']=='LITERATURE_NAME_IDENTITY'
    with pytest.raises(DomainError):checked_name_rows([{'text':'SYN 999','source_names':['N1'],'basis':'bad number'}],names)
