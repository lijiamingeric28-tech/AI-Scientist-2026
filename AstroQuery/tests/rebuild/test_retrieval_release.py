"""Formal release seams. Synthetic HTTP/PDF tests are not scientific validation."""
import asyncio
from copy import deepcopy

import httpx
import pymupdf
import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY, INSIGHT_RUN_POLICY, literature_strategy
from astroquery_ai.science.papers.download_support import bounded_download, enhanced
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from tests.rebuild.test_literature_lab_downloads import carrier


def test_frozen_release_and_legacy_are_separate_and_research_cannot_leak():
    spec={'run_policy':deepcopy(NORMAL_RUN_POLICY)}
    assert literature_strategy(spec)=={'P':'P0','S':'S2','F':'F1','D':'D1'}
    assert enhanced(spec)
    assert not literature_strategy({'run_policy':INSIGHT_RUN_POLICY})
    assert NORMAL_RUN_POLICY['insights']==INSIGHT_RUN_POLICY['insights']
    assert NORMAL_RUN_POLICY['scoring']['possible_points']==100
    assert spec['run_policy']['literature']['maximum_search_pages']==6
    spec['run_policy']['literature']['stop_after_materials']=True
    with pytest.raises(DomainError,match='research'):
        literature_strategy(spec)


@pytest.mark.parametrize('eligible,expected',[(10,'direct_next_page'),(9,'method')])
def test_formal_s2_uses_feedback_not_the_legacy_second_batch(tmp_path,monkeypatch,eligible,expected):
    from astroquery_ai.science.metadata_variants import batch_plan
    from tests.rebuild.test_two_tier_materials import carrier as preparation_carrier
    async def run():
        repo,tid,svc=preparation_carrier(tmp_path,count=0)
        spec=svc.spec(None,tid);spec['run_policy']=deepcopy(NORMAL_RUN_POLICY)
        main={'names':['Synthetic target'],'core_terms':['quantity'],'synonyms':[],
              'method_terms':['grounded method'],'query':'legacy query'}
        async def plan(*args,**kwargs):return main
        monkeypatch.setattr('astroquery_ai.science.metadata_preparation.term_plan',plan)
        result=await batch_plan(svc,repo.claim_job('formal',task_id=tid),spec,spec['properties'][0],2,
            feedback={'evaluated':40,'metadata_eligible':eligible,'attempted':eligible,'readable':0})
        assert result['retrieval_branch']==expected
        assert 'full:' not in result['query'] and 'abs:' in result['query']
        assert not spec['run_policy']['literature'].get('experiment')
    asyncio.run(run())


def test_four_properties_can_freeze_eighty_disjoint_works_without_global_forty_cap(tmp_path):
    """Synthetic controller boundary; acquisition evidence is tested separately."""
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.science.literature_preparation import prepare,schedule
    from tests.rebuild.test_two_tier_materials import carrier as preparation_carrier,settle_synthetic_downloads
    async def run():
        repo,tid,svc=preparation_carrier(tmp_path,properties=('p','q','r','s'),count=80)
        svc.spec(None,tid)['run_policy']=deepcopy(NORMAL_RUN_POLICY)
        with repo.transaction() as c:
            state=repo.objects(c,tid,'material_preparation')[0];state.update(protocol='metadata-materials/1',revision=2)
            for i,pool in enumerate(state['pools'].values()):
                works=['w'+str(n) for n in range(i*20,(i+1)*20)]
                pool.update(eligible=works,evaluated=works,batches_used=1)
            repo.put_object(c,tid,'material_preparation',tid,2,state)
        await prepare(svc,repo.claim_job('first',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('final',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            snap=repo.objects(c,tid,'candidate_snapshot')[0]
            assert snap['unique_works']==80 and snap['work_property_allocations']==80
            assert len(repo.objects(c,tid,'source'))==80
            assert all(len(a['property_ids'])==1 and a['source_ref'] for a in repo.objects(c,tid,'reading_allocation'))
            assert c.execute("select count(*) from jobs where task_id=? and kind='paper_batch'",(tid,)).fetchone()[0]==80
            assert len(snap['reading_allocation_refs'])==80
    asyncio.run(run())


def test_task_url_budget_survives_recovery_but_does_not_exhaust_next_task(tmp_path):
    async def run():
        app,tid,work,pdf=carrier(tmp_path);calls=[]
        def fail(request):
            calls.append(str(request.url));return httpx.Response(503)
        app.http.transport=httpx.MockTransport(fail)
        svc=PaperService(ScienceContext(app));job=app.repository.claim_job('first',task_id=tid)
        url='https://publisher.example/task-local.pdf'
        with pytest.raises(DomainError):await bounded_download(svc,job,work,url)
        assert len(calls)==2
        # New handler/lock state cannot reset the persisted logical acquisition.
        app.__dict__.pop('_download_locks',None)
        with pytest.raises(DomainError) as exhausted:
            await bounded_download(PaperService(ScienceContext(app)),job,work,url)
        assert exhausted.value.code=='DOWNLOAD_URL_EXHAUSTED'
        with app.repository.transaction() as c:app.repository.finish_job(c,job)
        app2,tid2,work2,_=carrier(tmp_path)
        def success(request):
            calls.append(str(request.url));return httpx.Response(200,content=pdf)
        app2.http.transport=httpx.MockTransport(success)
        svc2=PaperService(ScienceContext(app2));job2=app2.repository.claim_job('next',task_id=tid2)
        with pytest.raises(DomainError) as cooldown:
            await bounded_download(svc2,job2,work2,url)
        assert cooldown.value.code=='DOWNLOAD_URL_COOLDOWN'
        await asyncio.sleep(1.05)
        results=await asyncio.gather(*(bounded_download(svc2,job2,work2,url) for _ in range(2)))
        assert all(raw==pdf for raw,_ in results)
        assert len(calls)==3  # same-task concurrent duplicate reuses normal HTTP receipt
        with app2.repository.read() as c:
            attempts=app2.repository.objects(c,tid2,'download_url_attempt')
            assert attempts[0]['state']=='received'
            assert c.execute("select count(*) from objects where task_id=? and kind='download_url_attempt'",(tid,)).fetchone()[0]==4
    asyncio.run(run())


def pdf_with_version(version):
    text='A synthetic real acquisition title\nDOI: 10.1234/synthetic-lab\n'
    text+=('Accepted manuscript' if version=='accepted' else
           'Published 2025 October 1\nc2025 American Astronomical Society')
    with pymupdf.open() as doc:
        p=doc.new_page();p.insert_text((30,40),text);return doc.tobytes()


@pytest.mark.parametrize('higher_available',[True,False])
def test_lower_cached_version_allows_higher_path_and_verified_fallback(tmp_path,higher_available):
    async def run():
        app,tid,work,_=carrier(tmp_path)
        work['records'][0]['raw']['links_data']=[{'link_type':'AUTHOR_PDF','url':'https://publisher.example/accepted.pdf'}]
        with app.repository.transaction() as c:app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        def original(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            return httpx.Response(200,content=pdf_with_version('accepted'))
        app.http.transport=httpx.MockTransport(original)
        await PaperService(ScienceContext(app)).acquire_work(app.repository.claim_job('original',task_id=tid))
        with app.repository.read() as c:
            assert app.repository.objects(c,tid,'prepared_source')[0]['identity']['version_grade']=='accepted'
        app2,tid2,work2,_=carrier(tmp_path);seen=[]
        work2['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/published.pdf'}]
        with app2.repository.transaction() as c:app2.repository.put_object(c,tid2,'work',work2['work_id'],2,work2)
        def improved(request):
            if '/resolver/' in str(request.url):return httpx.Response(200,json={'links':{'records':[]}})
            seen.append(str(request.url))
            return httpx.Response(200,content=pdf_with_version('published')) if higher_available else httpx.Response(404)
        app2.http.transport=httpx.MockTransport(improved)
        await PaperService(ScienceContext(app2)).acquire_work(app2.repository.claim_job('upgrade',task_id=tid2))
        assert seen==['https://publisher.example/published.pdf']
        with app2.repository.read() as c:
            source=app2.repository.objects(c,tid2,'prepared_source')[0]
            assert source['identity']['version_grade']==('published' if higher_available else 'accepted')
            assert app2.repository.objects(c,tid2,'acquisition_result')[0]['state']=='acquired'
    asyncio.run(run())
