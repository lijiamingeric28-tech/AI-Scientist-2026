"""Synthetic protocol/recovery seams, not astrophysical validation."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import httpx
import pymupdf

from astroquery_ai.runtime.codec import canonical,digest,loads
from astroquery_ai.runtime.run_policy import INSIGHT_RUN_POLICY as NORMAL_RUN_POLICY
from astroquery_ai.science.literature import FairReadLedger
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from astroquery_ai.science.papers.download_support import landing_pdf_links,recovery_allowed
from tests.rebuild.scenario import application


def test_landing_links_are_explicit_bounded_and_not_script_or_http():
    raw=b'''<meta name="citation_pdf_url" content="/paper.pdf"><a href="javascript:download()">PDF</a>
        <a href="http://other.example/a.pdf">PDF</a><a href="other">Maybe paper</a>
        <a href="/download" type="application/pdf">PDF</a>'''
    assert landing_pdf_links(raw,'https://publisher.example/article')==[
        'https://publisher.example/paper.pdf','https://publisher.example/download']


def test_old_failure_needs_explicit_one_recovery_and_never_repeats_success():
    s={'run_policy':{'literature':{'experiment':{'D':'D1'}}}}
    j={'payload':{'acquisition_recovery_round':1,'recovery_reason':'verified new link'}}
    assert recovery_allowed(s,j,{'state':'failed'})
    assert not recovery_allowed(s,{'payload':{}},{'state':'failed'})
    assert not recovery_allowed(s,j,{'state':'acquired'})
    assert not recovery_allowed(s,j,{'state':'failed','recovery_round':1})
    assert not recovery_allowed({},j,{'state':'failed'})


def carrier(path):
    app=application(path);app.configuration.runtime['ads_api_token']='SYNTHETIC'
    tid=app.repository.create_task('SYNTHETIC material acquisition')['task_id']
    work={'work_id':'synthetic-work','allowed_property_ids':['synthetic-p'],
          'records':[{'bibcode':'SYNTHETIC-BIB','titles':['A synthetic real acquisition title'],
                      'dois':['10.1234/synthetic-lab'],'arxivs':[], 'raw':{}}]}
    policy=deepcopy(NORMAL_RUN_POLICY)
    policy['literature'].update(stop_after_materials=True,experiment={'D':'D1'})
    spec={'dependencies':[],'registry_release':{'id':'synthetic'},'run_policy':policy}
    spec['spec_hash']=digest(spec)
    ledger=FairReadLedger(['synthetic-p'],{'synthetic-p':['synthetic-work']},{'synthetic-work':['synthetic-p']})
    ledger.select()
    with app.repository.transaction() as c:
        ref=app.repository.put_object(c,tid,'confirmed_query','spec',1,spec)
        app.repository.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        app.repository.put_object(c,tid,'work',work['work_id'],1,work)
        app.repository.put_object(c,tid,'read_ledger',tid,1,asdict(ledger))
        app.repository.enqueue(c,tid,'M05','acquire_work',{'work_id':work['work_id']})
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((30,40),'A synthetic real acquisition title\nDOI: 10.1234/synthetic-lab')
        pdf=doc.tobytes()
    return app,tid,work,pdf


def test_official_resolver_landing_pdf_enters_normal_source_and_index(tmp_path):
    async def run():
        app,tid,work,pdf=carrier(tmp_path);seen=[]
        def response(request):
            seen.append(str(request.url))
            if '/resolver/' in str(request.url):
                return httpx.Response(200,json={'links':{'records':[{
                    'link_type':'ESOURCE|PUB_HTML','url':'https://publisher.example/article'}]}})
            if request.url.path=='/article':
                return httpx.Response(200,text='<meta name="citation_pdf_url" content="/paper.pdf">')
            return httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(response)
        service=PaperService(ScienceContext(app));job=app.repository.claim_job('synthetic',task_id=tid)
        await service.acquire_work(job)
        with app.repository.read() as c:
            result=app.repository.objects(c,tid,'acquisition_result')[0]
            assert result['state']=='acquired' and len(result['version_attempts'])==2
            assert app.repository.objects(c,tid,'document_index')[0]['page_count']==1
            assert len(app.repository.objects(c,tid,'prepared_source'))==1
            assert len(app.repository.objects(c,tid,'fulltext_link_lookup'))==1
            assert not c.execute("select 1 from jobs where task_id=? and kind in ('paper_batch','attachment_discover')",(tid,)).fetchone()
        assert len(seen)==3 and seen[-1]=='https://publisher.example/paper.pdf'
    asyncio.run(run())


def test_recovery_uses_new_verified_metadata_link_preserves_failure_version(tmp_path):
    async def run():
        app,tid,work,pdf=carrier(tmp_path);seen=[]
        def response(request):
            seen.append(str(request.url))
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            if request.url.path=='/new.pdf':return httpx.Response(200,content=pdf)
            return httpx.Response(404)
        work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/missing.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        app.http.transport=httpx.MockTransport(response);service=PaperService(ScienceContext(app))
        await service.acquire_work(app.repository.claim_job('first',task_id=tid))
        with app.repository.read() as c:assert app.repository.objects(c,tid,'acquisition_result')[0]['state']=='failed'
        work['records'][0]['raw']['links_data'].append({'link_type':'AUTHOR_PDF','url':'https://publisher.example/new.pdf'})
        with app.repository.transaction() as c:
            app.repository.put_object(c,tid,'work',work['work_id'],3,work)
            app.repository.enqueue(c,tid,'M05','acquire_work',{'work_id':work['work_id'],
                'acquisition_recovery_round':1,'recovery_reason':'New actual metadata link appeared'})
        await service.acquire_work(app.repository.claim_job('recovery',task_id=tid))
        with app.repository.read() as c:
            old=app.repository.object(c,tid,'acquisition_result',work['work_id'],1)
            current=app.repository.object(c,tid,'acquisition_result',work['work_id'])
            assert old['state']=='failed' and current['state']=='acquired'
            assert current['recovery_round']==1 and current['previous_result_version']==1
        assert sum(url.endswith('/missing.pdf') for url in seen)==1
    asyncio.run(run())


def test_common_exact_pdf_replay_requires_same_work_and_qualified_hash(tmp_path):
    from tests.support.literature.replay import ExactPDFHTTP
    async def run():
        app,tid,work,pdf=carrier(tmp_path);app.lab_pdf_cache_roots=[]
        work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/shared.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        def response(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            return httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(response)
        await PaperService(ScienceContext(app)).acquire_work(app.repository.claim_job('first',task_id=tid))
        with app.repository.transaction() as c:
            app.repository.enqueue(c,tid,'M05','acquire_work',{'work_id':work['work_id'],'diagnostic':'cache'})
        job=app.repository.claim_job('cache-check',task_id=tid)
        class Original:
            async def request(self,*a,**kw):raise AssertionError('Qualified exact original should be reused')
        http=ExactPDFHTTP(Original(),app,job)
        raw,metadata=await http.request(tid,'M05','publisher','GET','https://publisher.example/shared.pdf',
            max_bytes=50*1024**2,timeout=90,max_redirects=5,resource_scope='body')
        assert raw==pdf and metadata['lab_exact_pdf_cache'] and metadata['fresh_network_response'] is False
        assert metadata['source_task_id']==tid
    asyncio.run(run())


def test_real_printed_bibliographic_identifier_does_not_require_retrospective_doi_in_old_paper(tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.science.papers.download_support import printed_bibliographic_identity
    from astroquery_ai.science.documents import verify_work_identity
    from astroquery_ai.runtime.errors import DomainError
    async def run():
        work={'records':[{'bibcode':'SYNTHETIC-CODE-ONE','titles':['A sufficiently long synthetic historical paper title'],
                          'dois':['10.1234/retrospective'],'arxivs':[]}]}
        index={'page_count':1,'pages':[{'page':1,'text':'SYNTHETIC-CODE-ONE\nA sufficiently long synthetic historical paper title'}]}
        try:verify_work_identity(index,work)
        except DomainError as exc:original=exc
        else:raise AssertionError('Original D0 identifier requirement should remain unchanged')
        result=await printed_bibliographic_identity(SimpleNamespace(),{},index,work,original)
        assert result['state']=='verified' and result['bibcode_hits']==['SYNTHETIC-CODE-ONE']
        assert result['version_grade']=='unknown'
        wrong={**index,'pages':[{'page':1,'text':'SYNTHETIC-CODE-TWO\nA sufficiently long synthetic historical paper title'}]}
        try:await printed_bibliographic_identity(SimpleNamespace(),{},wrong,work,original)
        except DomainError:pass
        else:raise AssertionError('A different printed identifier is not permission')
    asyncio.run(run())


def test_qualified_cache_does_not_substitute_another_explicit_arxiv_revision():
    from astroquery_ai.science.papers.download_support import cached_revision_compatible
    work={'records':[{'arxivs':[('1234.5678',2)]}]}
    assert cached_revision_compatible(work,{'version_evidence':{'fragments':['arXiv:1234.5678v2']}})
    assert not cached_revision_compatible(work,{'version_evidence':{'fragments':['arXiv:1234.5678v1']}})
    assert not cached_revision_compatible(work,{'version_evidence':{'fragments':[]}})
    assert cached_revision_compatible({'records':[{'arxivs':[('1234.5678',None)]}]},{})


def test_transient_download_retries_once_then_commits_one_qualified_source(tmp_path):
    async def run():
        app,tid,work,pdf=carrier(tmp_path);calls=[]
        work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/transient.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        def response(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            calls.append(str(request.url))
            return httpx.Response(503) if len(calls)==1 else httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(response)
        await PaperService(ScienceContext(app)).acquire_work(app.repository.claim_job('temporary',task_id=tid))
        with app.repository.read() as c:
            assert app.repository.objects(c,tid,'acquisition_result')[0]['state']=='acquired'
            attempts=app.repository.objects(c,tid,'download_url_attempt')
            assert attempts[-1]['state']=='received'
            assert c.execute("select count(*) from http_attempts where task_id=? and service='publisher'",(tid,)).fetchone()[0]==2
            assert len(app.repository.objects(c,tid,'prepared_source'))==1
        assert len(calls)==2
    asyncio.run(run())


def test_rate_limit_is_not_hidden_retry_and_retains_failed_work_state(tmp_path):
    async def run():
        app,tid,work,pdf=carrier(tmp_path);calls=[]
        work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/limited.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        def response(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            calls.append(str(request.url));return httpx.Response(429,headers={'Retry-After':'2'})
        app.http.transport=httpx.MockTransport(response)
        await PaperService(ScienceContext(app)).acquire_work(app.repository.claim_job('limited',task_id=tid))
        with app.repository.read() as c:
            result=app.repository.objects(c,tid,'acquisition_result')[0]
            assert result['state']=='failed'
            assert result['version_attempts'][0]['reason']=='SOURCE_HTTP_ERROR'
            attempts=app.repository.objects(c,tid,'download_url_attempt')
            assert attempts[0]['details']['provider_status']==429
            assert attempts[0]['details']['retry_after_seconds']==2
            assert not app.repository.objects(c,tid,'prepared_source')
            assert FairReadLedger(**app.repository.objects(c,tid,'read_ledger')[0]).selections[work['work_id']]['state']=='released'
        assert len(calls)==1
    asyncio.run(run())


def test_corrupt_local_original_is_not_reused_and_reacquisition_restores_readable_slot(tmp_path):
    """Synthetic disk fault; real service must retain one verified download."""
    async def run():
        app,tid,work,pdf=carrier(tmp_path)
        work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/cached.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        calls=[]
        def response(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            calls.append(str(request.url));return httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(response)
        await PaperService(ScienceContext(app)).acquire_work(app.repository.claim_job('original',task_id=tid))
        with app.repository.transaction() as c:
            original=app.repository.objects(c,tid,'prepared_source')[0]
            app.repository.mutate_task(c,tid,lifecycle='paused')
        path=app.artifacts.path(original['artifact']['relative_path'])
        damaged=b'SYNTHETIC DISK CORRUPTION';path.write_bytes(damaged)
        app2,tid2,work2,_=carrier(tmp_path)
        work2['records'][0]['raw']['links_data']=work['records'][0]['raw']['links_data']
        with app2.repository.transaction() as c:app2.repository.put_object(c,tid2,'work',work2['work_id'],2,work2)
        app2.http.transport=httpx.MockTransport(response)
        await PaperService(ScienceContext(app2)).acquire_work(app2.repository.claim_job('recover-cache',task_id=tid2))
        with app2.repository.read() as c:
            result=app2.repository.objects(c,tid2,'acquisition_result')[0]
            assert result['state']=='acquired',result
            source=app2.repository.objects(c,tid2,'prepared_source')[0]
            assert len(app2.repository.objects(c,tid2,'document_index'))==1
            # Acquisition owns a material reservation; M06 is intentionally
            # not run and must not be reported as a completed reading.
            ledger=FairReadLedger(**app2.repository.objects(c,tid2,'read_ledger')[0])
            assert ledger.selections[work2['work_id']]['state']=='reserved'
            assert len(ledger.selections)==1
        assert app2.artifacts.path(source['artifact']['relative_path']).read_bytes()==pdf
        assert len(calls)==2
        assert any(p.read_bytes()==damaged for p in (app2.artifacts.root/'quarantine').glob('*') if p.is_file())
    asyncio.run(run())


def test_same_job_corrupt_http_cache_appends_recovery_and_keeps_original_receipts(tmp_path):
    from astroquery_ai.runtime.checkpoints import JobSteps
    async def run():
        app,tid,work,pdf=carrier(tmp_path);seen=[]
        def response(request):
            seen.append(str(request.url));return httpx.Response(200,content=pdf)
        app.http.transport=httpx.MockTransport(response)
        job=app.repository.claim_job('same-job-cache',task_id=tid)
        http=JobSteps(app).http(job)
        options=dict(max_bytes=1024**2,timeout=10,resource_scope='body',recover_unavailable_cache=True)
        raw,_=await http.request(tid,'M05','publisher','GET','https://publisher.example/recover.pdf',**options)
        with app.repository.read() as c:
            first=app.repository.objects(c,tid,'job_step')[0]
        app.artifacts.path(first['artifact']['relative_path']).write_bytes(b'SYNTHETIC CORRUPT RESPONSE')
        raw2,_=await http.request(tid,'M05','publisher','GET','https://publisher.example/recover.pdf',**options)
        assert raw==raw2==pdf and len(seen)==2
        with app.repository.read() as c:
            assert c.execute("select count(*) from objects where task_id=? and kind='job_step'",(tid,)).fetchone()[0]==2
            assert c.execute("select count(*) from objects where task_id=? and kind='http_response_cache'",(tid,)).fetchone()[0]==2
            assert app.repository.object(c,tid,'job_step',c.execute("select object_id from objects where task_id=? and kind='job_step' limit 1",(tid,)).fetchone()[0],1)==first
            assert not app.repository.objects(c,tid,'prepared_source')
        raw3,_=await http.request(tid,'M05','publisher','GET','https://publisher.example/recover.pdf',**options)
        assert raw3==pdf and len(seen)==2
    asyncio.run(run())
