"""Synthetic seam and protocol regressions; not real scientific acceptance."""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.codec import canonical,digest,loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY as NORMAL_RUN_POLICY
from astroquery_ai.runtime.service_routes import ServiceRoutes
from astroquery_ai.science.literature import FairReadLedger
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from astroquery_ai.science.workflow.literature_service import LiteratureService,checked_property_query
from astroquery_ai.science.catalog.extraction import identity_access_summary


def test_normal_acquisition_commits_source_and_two_property_batches(tmp_path):
    async def run():
        repo=Repository(tmp_path/'runtime.sqlite3');store=ArtifactStore(tmp_path/'artifacts',repo)
        tid=repo.create_task('SYNTHETIC normal acquisition seam')['task_id']
        work={'work_id':'synthetic-work','allowed_property_ids':['p1','p2'],
            'records':[{'titles':['A sufficiently long synthetic paper title'],'dois':[],
                        'arxivs':[('1234.5678',None)],'raw':{}}]}
        # Historical direct-acquisition seam. New material preparation defers
        # source publication until grants close and is covered by the current
        # consolidation tests/real short chain; retain this older path too.
        spec={'task_id':tid,'spec_id':'spec','dependencies':[],'registry_release':{'id':'synthetic'},
              'run_policy':{**NORMAL_RUN_POLICY,'literature':{'replacement':False}}}
        spec['spec_hash']=digest(spec)
        ledger=FairReadLedger(['p1','p2'],{'p1':[work['work_id']],'p2':[work['work_id']]},{work['work_id']:['p1','p2']})
        ledger.select()
        with repo.transaction() as c:
            ref=repo.put_object(c,tid,'confirmed_query','spec',1,spec)
            repo.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
            repo.put_object(c,tid,'work',work['work_id'],1,work)
            repo.put_object(c,tid,'read_ledger',tid,1,asdict(ledger))
            repo.enqueue(c,tid,'M05','acquire_work',{'work_id':work['work_id']})
        calls=[]
        async def request(*args,**kwargs):calls.append(args);return b'%PDF-SYNTHETIC',{'status':200}
        index={'page_count':2,'pages':[{'page':1,'text':'A sufficiently long synthetic paper title\narXiv:1234.5678v1'},
                                     {'page':2,'text':'SYNTHETIC body'}]}
        async def parse(*args,**kwargs):return index
        app=SimpleNamespace(repository=repo,artifacts=store,configuration=SimpleNamespace(runtime={}),parse_owned=parse)
        ctx=ScienceContext(app);ctx.steps=SimpleNamespace(http=lambda job:SimpleNamespace(request=request))
        service=PaperService(ctx);job=repo.claim_job('worker',lease_seconds=600)
        await service.acquire_work(job)
        with repo.read() as c:
            assert len(repo.objects(c,tid,'source'))==1
            assert len(repo.objects(c,tid,'qualification'))==1
            assert len(repo.objects(c,tid,'document_index'))==1
            jobs=[dict(r) for r in c.execute('select kind,payload from jobs where task_id=?',(tid,))]
            batches=[loads(r['payload']) for r in jobs if r['kind']=='paper_batch']
            assert {tuple(b['property_ids']) for b in batches}=={('p1',),('p2',)}
            assert len({b['reading_batch_id'] for b in batches})==2
            assert len({b['artifact_ref'] for b in batches})==1
            assert sum(r['kind']=='attachment_discover' for r in jobs)==1
            assert repo.objects(c,tid,'acquisition_result')[0]['state']=='acquired'
        assert len(calls)==1
    asyncio.run(run())


def test_expression_repair_receives_original_and_diagnostic_then_global_filter(tmp_path):
    from tests.rebuild.test_literature_selection import spec
    async def run():
        repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC syntax repair')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open')
            repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('worker');seen=[]
        class Steps:
            async def model(self,execution,**kwargs):
                body=loads(kwargs['messages'][-1]['content']);seen.append(body)
                if len(seen)==1:return {'query':'abs:log10(age)','intent':'SYNTHETIC'}, {'attempt_id':'first'}
                feedback=body['feedback']
                assert feedback['model_expression']=='abs:log10(age)'
                assert feedback['message']=='所有检索词必须有明确字段'
                assert feedback['error_token']=='age' and 'syntax' in feedback
                return {'query':'abs:"Object A" OR body:"quantity (native)"','intent':'SYNTHETIC'}, {'attempt_id':'second'}
            def http(self,job):return self
            async def request(self,*args,**kwargs):
                assert kwargs['params']['q']=='(abs:"Object A" OR body:"quantity (native)") AND doctype:(article OR eprint)'
                assert kwargs['params']['rows']=='40'
                return canonical({'response':{'docs':[]}}),{'status':200}
        store=ArtifactStore(tmp_path/'artifacts',repo)
        app=SimpleNamespace(artifacts=store,configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))
        service=LiteratureService(SimpleNamespace(app=app,repo=repo,steps=Steps(),extractor=None))
        docs,closure=await service.property_query(job,spec(),spec()['properties'][0])
        assert not docs and closure['state']=='checked' and len(closure['expression_attempts'])==2
    asyncio.run(run())


def test_unavailable_routes_are_shared_and_recovery_remains_possible():
    async def run():
        class HTTP:
            def __init__(self):self.calls=[];self.recovered=False
            async def request(self,tid,owner,service,method,endpoint,**kwargs):
                self.calls.append(endpoint)
                if not self.recovered:raise DomainError('SOURCE_HTTP_TIMEOUT','SYNTHETIC')
                return b'<VOTABLE/>',{'status':200}
        http=HTTP();routes=ServiceRoutes(http)
        async def one():
            with pytest.raises(DomainError) as exc:
                await routes.request('t','M03','vizier','votable_data',['a','b','c'],'GET')
            assert exc.value.code=='CATALOG_ENDPOINTS_UNAVAILABLE'
        await asyncio.gather(*(one() for _ in range(4)))
        assert len(http.calls)==6
        await one();assert len(http.calls)==6
        state=routes.state('t','vizier','votable_data');state['unavailable_until']=0
        for v in state['nodes'].values():v['cool_until']=0
        http.recovered=True
        assert (await routes.request('t','M03','vizier','votable_data',['a','b','c'],'GET'))[1]['status']==200
        assert routes.state('t','vizier','votable_metadata')['preferred'] is None
    asyncio.run(run())


def test_catalog_access_summary_distinguishes_access_empty_rows_and_identity():
    failed={'state':'failed','returned_row_count':0,'verified_row_count':0}
    empty={'state':'no_verified_target_row','response_artifact':{'id':'synthetic'},'returned_row_count':0,'verified_row_count':0}
    ambiguous={**empty,'state':'ambiguous_identity','returned_row_count':2}
    assert identity_access_summary([failed],has_properties=True)['identity_gap']=='catalog_access_incomplete'
    assert identity_access_summary([empty],has_properties=True)['identity_gap']=='successful_queries_returned_zero_rows'
    assert identity_access_summary([ambiguous],has_properties=True)['identity_gap']=='identity_unresolved_in_returned_rows'
    assert identity_access_summary([],has_properties=False)['property_columns_state']=='missing'
    assert identity_access_summary([{**empty,'state':'verified_target_rows','verified_row_count':1}],has_properties=True)['identity_gap'] is None


def test_short_title_needs_real_identifier_and_numbered_bibliography_is_not_body_citation():
    from astroquery_ai.science.documents import verify_work_identity
    from astroquery_ai.science.papers.references import bibliography_entries
    work={'records':[{'titles':['Short title'],'dois':[],'arxivs':[('1234.5678',None)]}]}
    index={'page_count':1,'pages':[{'page':1,'text':'Short title\narXiv:1234.5678v1'}]}
    assert verify_work_identity(index,work)['arxiv_hits']==['1234.5678']
    with pytest.raises(DomainError):verify_work_identity({'page_count':1,'pages':[{'page':1,'text':'Short title'}]},work)
    text='Body quote\n[16] a source mentioned in 2021\nSome intervening text\n[9] another in 2000\nEnd of body\n[1] A. Actual, Journal 10, 20 (1996).\n[2] B. Actual, Journal 11, 21 (2001).'
    entries=bibliography_entries({'pages':[{'text':text}]})
    assert len(entries)==2 and entries[0].startswith('[1]') and 'Body quote' not in entries[0]


@pytest.mark.parametrize('source_kind',['paper','catalog'])
def test_real_bibliography_zero_rule_matches_get_one_combined_model_choice(tmp_path,source_kind):
    from tests.rebuild.test_bounded_reading import fixture
    async def run():
        app,service,tid,calls=fixture(tmp_path,'empty');repo=app.repository
        await service.extract_paper(repo.claim_job('worker',lease_seconds=600))
        quote='The measurement is attributed to TWB.'
        entry='[1] Smith, A. 2020, doi:10.1234/example'
        source_id='synthetic-source' if source_kind=='paper' else 'synthetic-catalog-reference-source'
        if source_kind=='catalog':artifact=app.artifacts.write((quote+'\nReferences:\n'+entry).encode(),'text/plain')
        with repo.transaction() as c:
            if source_kind=='paper':
                repo.put_object(c,tid,'document_index',source_id,2,{'pages':[{'page':1,'text':quote+'\nReferences\n'+entry}]})
            else:
                app.artifacts.register(c,tid,'synthetic-readme',artifact)
                repo.put_object(c,tid,'source',source_id,1,{'source_id':source_id,'kind':'catalog','metadata':{
                    'catalog_document':{'artifact_ref':{'id':artifact['artifact_id']}}}})
            for n in range(2):repo.put_object(c,tid,'reported_source_ref',str(n),1,{'reference_id':str(n),
                'source_ref':{'id':source_id},'raw_code':'TWB','link_quote':quote,'revision':1})
            repo.enqueue(c,tid,'M06','citation_enrich',{'work_id':source_id})
        model_calls=[];http_calls=[]
        async def model(**kwargs):
            model_calls.append(kwargs);assert kwargs['profile'].version=='citation-resolution-2'
            return {'matches':[{'reference':r,'choice':'E1','entry_quote':entry} for r in ('R1','R2')]},{'attempt_id':'synthetic-batch-choice'}
        async def request(*args,**kwargs):
            http_calls.append(kwargs)
            return canonical({'response':{'docs':[{'bibcode':'2020SYNTHETIC....1S','doi':['10.1234/example'],
                'title':['SYNTHETIC'], 'abstract':'SYNTHETIC background'}]}}),{}
        app.models.json=model;app.configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'});app.http=SimpleNamespace(request=request)
        while (job:=repo.claim_job('worker',lease_seconds=600)) and job['kind']!='citation_enrich':
            with repo.transaction() as c:repo.finish_job(c,job)
        await service.enrich_references(job)
        assert len(model_calls)==1 and len(http_calls)==1
        with repo.read() as c:
            assert all(r['resolution_state']=='resolved' for r in repo.objects(c,tid,'reported_source_ref'))
            assert not repo.objects(c,tid,'measurement') and not repo.objects(c,tid,'acquisition_result')
            if source_kind=='catalog':assert not any(d.get('source_id')==source_id for d in repo.objects(c,tid,'document_index'))
    asyncio.run(run())


def test_ads_400_keeps_bounded_diagnostic_without_authorization(tmp_path):
    import httpx
    from tests.rebuild.scenario import application
    async def run():
        app=application(tmp_path);tid=app.repository.create_task('SYNTHETIC ADS diagnostic',kind='validation')['task_id']
        with app.repository.transaction() as c:
            app.repository.put_object(c,tid,'calibration_scope',tid,1,{'allowed_owners':['M04'],
                'allowed_services':['ads'],'max_requests':3})
        app.http.transport=httpx.MockTransport(lambda request:httpx.Response(400,
            text='Invalid query parentheses. Bearer SYNTHETIC_SECRET '+('x'*6000)))
        with pytest.raises(DomainError) as exc:
            await app.http.request(tid,'M04','ads','GET','https://api.adsabs.harvard.edu/v1/search/query',
                headers={'Authorization':'Bearer SYNTHETIC_SECRET'})
        assert exc.value.details['provider_status']==400
        diagnostic=exc.value.details['provider_error']
        assert 'Invalid query parentheses' in diagnostic and 'SYNTHETIC_SECRET' not in diagnostic
        assert len(diagnostic)<=4096
    asyncio.run(run())


def test_parallel_literature_unit_wait_keeps_parent_lease_and_sibling_results(tmp_path):
    from astroquery_ai.runtime.throughput import DispatchDeferred
    from tests.rebuild.test_literature_selection import spec
    from copy import deepcopy
    async def run():
        repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC coordinated wait')['task_id']
        data=spec();a=data['properties'][0];a['definition']['family_id']='synthetic-family'
        b=deepcopy(a);b['property_id']='synthetic-other';data['properties']=[a,b]
        data['spec_hash']=digest(data)
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open')
            repo.enqueue(c,tid,'M04','literature_discover',{})
        job=repo.claim_job('worker',lease_seconds=600);calls=[];sibling_done=asyncio.Event()
        service=LiteratureService(SimpleNamespace(app=None,repo=repo,steps=None,extractor=None,
            spec=lambda c,t:data))
        async def query(execution,full,binding):
            pid=binding['property_id'];calls.append(pid)
            if pid==a['property_id'] and calls.count(pid)==1:
                await sibling_done.wait()
                raise DispatchDeferred('model-rate:SYNTHETIC',.05)
            if pid==b['property_id']:sibling_done.set()
            return [],{'state':'checked'}
        service.property_query=query
        await service.discover_literature(job)
        with repo.read() as c:
            assert c.execute('select status from jobs where job_id=?',(job['job_id'],)).fetchone()[0]=='succeeded'
            snapshot=repo.objects(c,tid,'candidate_snapshot')[0]
            assert len(snapshot['property_plans'])==2
            assert repo.objects(c,tid,'literature_search_plan')
            assert c.execute('select count(*) from attempts').fetchone()[0]==0
        assert calls.count(b['property_id'])==1 and calls.count(a['property_id'])==2
    asyncio.run(run())


@pytest.mark.parametrize('kind',['literature_discover','citation_enrich'])
def test_coordinator_wait_preserves_the_exact_call_and_its_sibling_checkpoint(tmp_path,kind):
    from astroquery_ai.runtime.checkpoints import JobSteps
    from astroquery_ai.runtime.calls import ModelProfile
    from astroquery_ai.runtime.throughput import DispatchDeferred
    async def run():
        repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC call-level wait')['task_id']
        with repo.transaction() as c:repo.enqueue(c,tid,'M04',kind,{})
        job=repo.claim_job('worker',lease_seconds=600);calls=[];sibling_saved=asyncio.Event()
        class Model:
            async def json(self,**kwargs):
                prompt=kwargs['messages'][0]['content'];calls.append(prompt)
                if prompt=='pending-specific-repair' and calls.count(prompt)==1:
                    await sibling_saved.wait();raise DispatchDeferred('model-rate:SYNTHETIC',.05)
                return {'actual_input':prompt},{'attempt_id':'synthetic-'+prompt}
        steps=JobSteps(SimpleNamespace(repository=repo,models=Model()))
        async def one(prompt):
            result=await steps.model(job,task_id=tid,owner='M04',root_id=prompt,
                profile=ModelProfile(model='synthetic',operation='test'),messages=[{'role':'user','content':prompt}])
            if prompt=='successful-sibling':sibling_saved.set()
            return result
        results=await asyncio.gather(one('pending-specific-repair'),one('successful-sibling'))
        assert [r[0]['actual_input'] for r in results]==['pending-specific-repair','successful-sibling']
        assert calls.count('successful-sibling')==1 and calls.count('pending-specific-repair')==2
        with repo.read() as c:
            assert len(repo.objects(c,tid,'job_step'))==2
            repo.validate_lease(c,job,scientific=False)
    asyncio.run(run())
