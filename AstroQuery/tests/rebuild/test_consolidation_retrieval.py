"""backend-consolidation/1 bounded metadata contracts; synthetic, no network."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from astroquery_ai.runtime.codec import canonical,loads
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
from astroquery_ai.science.literature import parse_record
from astroquery_ai.science.literature_selection import relevance_bindings,relevance_outcome
from astroquery_ai.science.metadata_preparation import compile_metadata_query,fetch_batch
from astroquery_ai.science.workflow.literature_service import LiteratureService
from tests.rebuild.test_two_tier_materials import document,configuration,carrier,settle_synthetic_downloads


def spec():
    value=configuration();value['run_policy']=deepcopy(CONSOLIDATION_RUN_POLICY);return value


def test_exact_names_normalized_only_in_query_and_core_terms_stay_data():
    plan={'names':['  Object  −42 A  ','Name "quoted"'],'phrases':['native quantity','method (calibrated)']}
    q=compile_metadata_query(plan)
    assert '=abs:("Object −42 A" OR "Name \\"quoted\\"")' in q
    assert ' AND abs:(' in q and q.endswith('AND doctype:(article OR eprint)')
    assert plan['names'][0]=='  Object  −42 A  '
    assert 'full:' not in q and 'body:' not in q


def test_no_implicit_fulltext_permission_and_keywords_are_real_evidence():
    s=spec();work={'work_id':'w','records':[parse_record({**document(1),'abstract':None,'keyword':['Target membership; synthetic quantity']})]}
    scope,wire=relevance_bindings(s,[work]);assert wire['W1'][0]['evidence'][-1]['field']=='keyword'
    row={'id':'W1','decision':'needs_fulltext','properties':[],'evidence':[],'rank':1,'reason':'plausible only'}
    assert relevance_outcome({'works':[row]},[work],s)['unresolved_ids']==['w']
    row.update(properties=['P1'],evidence=[wire['W1'][0]['evidence'][-1]['id']])
    assert relevance_outcome({'works':[row]},[work],s)['decisions']['w']['property_ids']==['p']
    row.update(decision='unassessable',properties=[],evidence=[])
    assert relevance_outcome({'works':[row]},[work],s)['decisions']['w']['property_ids']==[]


def test_three_batches_keep_unassessed_overflow_dedup_and_query_cache(tmp_path):
    async def run():
        repo=Repository(tmp_path/'db');store=ArtifactStore(tmp_path/'artifacts',repo);s=spec()
        tid=repo.create_task('SYNTHETIC metadata paging')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open');repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('synthetic',lease_seconds=600);calls=[];models=[]
        class Steps:
            async def model(self,execution,**kw):
                body=loads(kw['messages'][0]['content']);models.append(body)
                return {'target_name_labels':['N1'],'core_terms':['new-method' if body['rewrite'] else 'ordinary quantity'],
                    'synonyms':[],'method_terms':[],'intent':'SYNTHETIC','rewrite_useful':True},{'attempt_id':'synthetic'}
            def http(self,execution):return self
            async def request(self,*args,**kw):
                q=kw['params']['q'];start=int(kw['params']['start']);calls.append((q,start))
                if 'new-method' in q:docs=[document(i) for i in (range(0,40) if start==0 else range(100,140))]
                elif start==0:docs=[document(i,v) for i in range(20) for v in (1,2)]
                else:docs=[document(i) for i in range(start-20,start+20)]
                return canonical({'response':{'docs':docs,'numFound':500}}),{'status':200}
        svc=LiteratureService(SimpleNamespace(repo=repo,steps=Steps(),extractor=None,
            app=SimpleNamespace(artifacts=store,configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))))
        batches=[];records=[]
        for n in (1,2,3):
            layer=await fetch_batch(svc,job,s,s['properties'][0],n,records,{'readable':3})
            assert len(layer['works'])==40
            assert not set(r['bibcode'] for r in records)&set(r['bibcode'] for r in layer['records'])
            records.extend(layer['records']);batches.append(layer)
        assert len({w['work_id'] for b in batches for w in b['works']})==120
        assert len(calls)==5 and len(models)==2
        assert [v for _,v in calls[:3]]==[0,40,80]
        await fetch_batch(svc,job,s,s['properties'][0],3,records)
        assert len(calls)==5 and len(models)==2
    asyncio.run(run())


def test_download_backups_close_without_extra_search_and_keep_shared_grants(tmp_path):
    from astroquery_ai.science.literature_preparation import prepare,schedule
    async def run():
        repo,tid,svc=carrier(tmp_path,properties=('p','q'));oldspec=svc.spec(None,tid)
        oldspec['run_policy']=deepcopy(CONSOLIDATION_RUN_POLICY)
        with repo.transaction() as c:
            state=repo.objects(c,tid,'material_preparation')[0];state.update(protocol='metadata-materials/1',revision=2)
            for pool in state['pools'].values():pool.update(batches_used=1)
            repo.put_object(c,tid,'material_preparation',tid,2,state)
        await prepare(svc,repo.claim_job('synthetic',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid,fail={'w0'})
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('synthetic',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('synthetic',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            state=repo.objects(c,tid,'material_preparation')[0]
            assert state['closed'] and len(state['final_allocations'])==20
            assert all(pool['batches_used']==1 for pool in state['pools'].values())
            assert all(set(a['property_ids'])=={'p','q'} for a in repo.objects(c,tid,'reading_allocation'))
    asyncio.run(run())


def test_paging_stops_on_repetition_and_no_useful_rewrite(tmp_path):
    async def run():
        repo=Repository(tmp_path/'db');store=ArtifactStore(tmp_path/'artifacts',repo);s=spec()
        tid=repo.create_task('SYNTHETIC bounded repetition')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open');repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('synthetic',lease_seconds=600);calls=[]
        class Steps:
            async def model(self,execution,**kw):
                b=loads(kw['messages'][0]['content'])
                return {'target_name_labels':['N1'],'core_terms':['ordinary quantity'],'intent':'SYNTHETIC',
                    'rewrite_useful':not b['rewrite']},{'attempt_id':'synthetic'}
            def http(self,execution):return self
            async def request(self,*args,**kw):
                calls.append(kw['params']);return canonical({'response':{'docs':[document(i,v) for i in range(20) for v in (1,2)],'numFound':500}}),{}
        svc=LiteratureService(SimpleNamespace(repo=repo,steps=Steps(),extractor=None,
            app=SimpleNamespace(artifacts=store,configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))))
        first=await fetch_batch(svc,job,s,s['properties'][0],1)
        assert first['closure']=='provider_repeated_page' and len(first['works'])==20 and len(calls)==2
        second=await fetch_batch(svc,job,s,s['properties'][0],2,first['records'])
        assert not second['works'] and len(calls)==2
        third=await fetch_batch(svc,job,s,s['properties'][0],3,first['records'])
        assert third['closure']=='no_useful_rewrite' and len(calls)==2
    asyncio.run(run())


def test_resource_wait_is_not_a_network_retry_and_real_failure_is_bounded(tmp_path):
    from astroquery_ai.runtime.throughput import DispatchDeferred
    from astroquery_ai.runtime.errors import DomainError
    async def run():
        repo=Repository(tmp_path/'db');store=ArtifactStore(tmp_path/'artifacts',repo);s=spec()
        tid=repo.create_task('SYNTHETIC resource and I/O boundaries')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open');repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('synthetic',lease_seconds=600);calls=[]
        class Steps:
            async def model(self,execution,**kw):
                return {'target_name_labels':['N1'],'core_terms':['quantity'],'intent':'SYNTHETIC'},{'attempt_id':'synthetic'}
            def http(self,execution):return self
            async def request(self,*args,**kw):
                calls.append(kw['params'])
                if len(calls)==1:raise DispatchDeferred('synthetic-resource',.1)
                raise DomainError('SOURCE_HTTP_TIMEOUT','SYNTHETIC actual I/O failure')
        svc=LiteratureService(SimpleNamespace(repo=repo,steps=Steps(),extractor=None,
            app=SimpleNamespace(artifacts=store,configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))))
        import pytest
        with pytest.raises(DispatchDeferred):await fetch_batch(svc,job,s,s['properties'][0],1)
        with repo.read() as c:assert repo.objects(c,tid,'literature_search')[0]['page_attempts']['0']==0
        result=await fetch_batch(svc,job,s,s['properties'][0],1)
        assert result['closure']=='service_failure' and len(calls)==3
        await fetch_batch(svc,job,s,s['properties'][0],1)
        assert len(calls)==3
    asyncio.run(run())
