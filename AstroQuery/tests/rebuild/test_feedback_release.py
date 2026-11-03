"""Unpaid production-entry controls; semantic replies below are synthetic."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pymupdf
import pytest

from astroquery_ai.runtime.codec import canonical, digest, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import request_policy
from astroquery_ai.science.papers.acquisition import verify_identity_and_body, body_identity_pages
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from tests.rebuild.test_literature_lab_downloads import carrier


TITLE='A synthetic real acquisition title'
TEXT=TITLE+'\nDOI: 10.1234/synthetic-lab\n'+('Actual observations and data reduction. '*12)+'\nResults and discussion.\nReferences.'


@pytest.mark.parametrize('form,expected', [('complete_manuscript',None),('abstract_only','DOCUMENT_ABSTRACT_ONLY'),
    ('incomplete','DOCUMENT_INCOMPLETE'),('unknown','DOCUMENT_COMPLETENESS_UNRESOLVED')])
def test_identity_is_not_a_body_shortcut_and_one_page_can_be_complete(form,expected):
    async def run():
        calls=[]
        class Steps:
            async def model(self,*args,**kw):
                calls.append(kw)
                return {'same_title':True,'printed_title_quote':TITLE,'page':1,'document_form':form,
                    'form_evidence':{'page':1,'quote':'Results and discussion.'}}, {'attempt_id':'synthetic'}
        svc=SimpleNamespace(steps=Steps(),model_profile=lambda *a,**kw:kw)
        work={'work_id':'synthetic','records':[{'titles':[TITLE],'dois':['10.1234/synthetic-lab'],'arxivs':[]}]}
        index={'page_count':1,'sha256':'synthetic','pages':[{'page':1,'text':TEXT}]}
        if expected:
            with pytest.raises(DomainError) as e:await verify_identity_and_body(svc,{'task_id':'synthetic'},index,work)
            assert e.value.code==expected
        else:
            result=await verify_identity_and_body(svc,{'task_id':'synthetic'},index,work)
            assert result['manuscript']['state']=='complete' and result['title_hits']
        assert len(calls)==(2 if form=='unknown' else 1)
        assert all(c['root_limit']==2 for c in calls)
    asyncio.run(run())


def test_unbound_form_quote_cannot_grant_body_and_front_tail_are_bounded():
    async def run():
        calls=[]
        class Steps:
            async def model(self,*a,**kw):
                calls.append(kw)
                return {'same_title':True,'printed_title_quote':TITLE,'page':1,'document_form':'complete_manuscript',
                    'form_evidence':{'page':1,'quote':'not present in this PDF'}},{'attempt_id':'synthetic'}
        svc=SimpleNamespace(steps=Steps(),model_profile=lambda *a,**kw:kw)
        index={'page_count':4,'sha256':'synthetic','pages':[{'page':i,'text':TEXT+'中文'*50000} for i in range(1,5)]}
        for expanded in (False,True):
            assert sum(len(p['text'].encode()) for p in body_identity_pages(index,expanded))<=22000
        with pytest.raises(DomainError) as e:
            await verify_identity_and_body(svc,{'task_id':'synthetic'},index,{'work_id':'w','records':[]})
        assert e.value.code=='DOCUMENT_COMPLETENESS_UNRESOLVED' and len(calls)==2
    asyncio.run(run())


@pytest.mark.parametrize('form,page_count', [('abstract_only',1),('complete_manuscript',1),('complete_manuscript',51)])
def test_normal_acquire_entry_body_quota_and_long_separation(tmp_path,form,page_count):
    async def run():
        app,tid,work,_=carrier(tmp_path)
        with app.repository.transaction() as c:
            spec=app.repository.objects(c,tid,'confirmed_query')[0]
            spec['run_policy']=request_policy(SimpleNamespace(runtime={}))
            spec.pop('spec_hash');spec['spec_hash']=digest(spec)
            ref=app.repository.put_object(c,tid,'confirmed_query','spec',2,spec)
            app.repository.mutate_task(c,tid,query_ref=canonical(ref).decode())
            work['records'][0]['raw']['links_data']=[{'link_type':'PUB_PDF','url':'https://publisher.example/paper.pdf'}]
            app.repository.put_object(c,tid,'work',work['work_id'],2,work)
        with pymupdf.open() as pdf:
            for _ in range(page_count):pdf.new_page().insert_text((30,40),TEXT)
            raw=pdf.tobytes()
        def transport(req):
            if '/resolver/' in str(req.url):return httpx.Response(200,json={'links':{'records':[]}})
            return httpx.Response(200,content=raw)
        app.http.transport=httpx.MockTransport(transport)
        svc=PaperService(ScienceContext(app));calls=[]
        async def model(*a,**kw):
            calls.append(kw)
            return {'same_title':True,'printed_title_quote':TITLE,'page':1,'document_form':form,
                'form_evidence':{'page':1,'quote':'Results and discussion.'}},{'attempt_id':'synthetic'}
        svc.steps.model=model
        await svc.acquire_work(app.repository.claim_job('synthetic',task_id=tid,lease_seconds=600))
        with app.repository.read() as c:
            result=app.repository.objects(c,tid,'acquisition_result')[0]
            assert not c.execute("SELECT 1 FROM attempts WHERE task_id=?",(tid,)).fetchone()
            assert not c.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('paper_batch','attachment_discover')",(tid,)).fetchone()
            if form=='abstract_only':
                assert result['state']=='failed'
                assert any(v.get('reason')=='DOCUMENT_ABSTRACT_ONLY' for v in result['version_attempts'])
                assert app.repository.objects(c,tid,'read_ledger')[0]['selections'][work['work_id']]['state']=='released'
                assert not app.repository.objects(c,tid,'prepared_source')
            elif page_count>50:
                assert result['state']=='skipped' and any(x.get('verified_long_download') for x in result['skipped_versions'])
                assert not app.repository.objects(c,tid,'prepared_source')
            else:
                assert result['state']=='acquired'
                assert app.repository.objects(c,tid,'prepared_source')[0]['identity']['manuscript']['state']=='complete'
        if form=='complete_manuscript' and page_count==1:
            from astroquery_ai.science.literature_preparation import finalize
            from astroquery_ai.science.workflow.literature_service import LiteratureService
            service=LiteratureService(ScienceContext(app))
            pool={'acquired':[work['work_id']],'evaluated':[work['work_id']],'attempted':[work['work_id']],
                  'long_downloaded':[],'decisions':{work['work_id']:{'decision':'needs_fulltext'}}}
            state={'revision':1,'protocol':'metadata-materials/1','pools':{p:deepcopy(pool) for p in ('synthetic-p','synthetic-q')}}
            with app.repository.transaction() as c:
                finalize(service,c,tid,spec,state)
            with app.repository.read() as c:
                snapshot=app.repository.objects(c,tid,'candidate_snapshot')[0]
                assert snapshot['downstream_scheduled'] and snapshot['unique_works']==1
                assert snapshot['work_property_allocations']==2
                assert snapshot['property_material_counts']=={p:{'D':1,'L':0,'F':1} for p in state['pools']}
                assert len(snapshot['reading_allocation_refs'])==1
                jobs=[loads(r[0]) for r in c.execute("SELECT payload FROM jobs WHERE task_id=? AND kind='paper_batch'",(tid,))]
                assert {tuple(j['property_ids']) for j in jobs}=={('synthetic-p',),('synthetic-q',)}
                assert c.execute("SELECT count(*) FROM jobs WHERE task_id=? AND kind='attachment_discover'",(tid,)).fetchone()[0]==1
                source=app.repository.objects(c,tid,'source')[0]
                allocation=app.repository.objects(c,tid,'reading_allocation')[0]
                assert allocation['artifact_sha256']==source['artifact']['sha256']
                assert set(source['work']['allowed_property_ids'])==set(state['pools'])
        assert calls
    asyncio.run(run())
