"""Route recovery must be tested inside the real timed catalog job context."""
import asyncio
from collections import Counter

import httpx
import pytest

from astroquery_ai.runtime.codec import canonical,digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import request_policy,current_job,ensure_window,endpoint_cooling,cool_endpoint
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.service_routes import ServiceRoutes

ENDPOINTS=['https://vizier.cds.unistra.fr/viz-bin/votable',
           'https://vizier.cfa.harvard.edu/viz-bin/votable',
           'https://vizier.idia.ac.za/viz-bin/votable']

def setup(tmp_path,handler):
    app=Application(tmp_path)
    tid=app.repository.create_task('SYNTHETIC timed route recovery')['task_id']
    with app.repository.transaction() as c:
        app.repository.put_object(c,tid,'calibration_scope',tid,1,
            {'allowed_owners':['M03'],'allowed_services':['vizier'],'max_requests':40})
    app.http.transport=httpx.MockTransport(handler)
    return app,tid,ServiceRoutes(app.http)


def catalog_job(app,tid):
    repo=app.repository
    with repo.transaction() as conn:
        spec={'run_policy':request_policy(app.configuration),'properties':[], 'dependencies':[],
              'registry_release':{'id':'SYNTHETIC'}}
        spec['spec_hash']=digest(spec)
        ref=repo.put_object(conn,tid,'confirmed_query',tid,1,spec)
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        repo.producer(conn,tid,'synthetic_hold')
        repo.enqueue(conn,tid,'M03','catalog_discover',{})
    job=repo.claim_job('synthetic-worker')
    with repo.transaction() as conn:assert ensure_window(repo,conn,job)
    return job


def test_timed_catalog_retains_managed_second_round_recovery(tmp_path):
    async def run():
        counts=Counter()
        async def handler(request):
            host=request.url.host;counts[host]+=1
            if host!='vizier.idia.ac.za' or counts[host]==1:
                raise httpx.ConnectTimeout('SYNTHETIC transient',request=request)
            return httpx.Response(200,content=b'<VOTABLE><RESOURCE name="SYNTHETIC"/></VOTABLE>')
        app,tid,routes=setup(tmp_path,handler)
        token=current_job.set(catalog_job(app,tid))
        try:
            await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC','-out.max':'0'})
            assert sorted(counts.values())==[2,2,2]
            raw,meta=await routes.request(tid,'M03','vizier','votable_metadata',ENDPOINTS,'GET',params={'-source':'SYNTHETIC'})
            assert b'SYNTHETIC' in raw and meta['selected_route']==ENDPOINTS[2]
            with app.repository.read() as c:assert not app.repository.objects(c,tid,'endpoint_cooldown')
        finally:current_job.reset(token)
    asyncio.run(run())


def test_managed_metadata_can_recover_from_historical_search_cooldown(tmp_path):
    async def run():
        visited=[]
        async def handler(request):
            visited.append(request.url.host)
            return httpx.Response(200,content=b'<VOTABLE><RESOURCE name="SYNTHETIC"/></VOTABLE>')
        app,tid,routes=setup(tmp_path,handler)
        token=current_job.set(catalog_job(app,tid))
        try:
            cool_endpoint(app.repository,tid,'vizier',ENDPOINTS[0],'SOURCE_HTTP_TIMEOUT')
            assert endpoint_cooling(app.repository,tid,'vizier',ENDPOINTS[0])
            state=routes.state(tid,'vizier','votable_metadata');state.update(preferred=ENDPOINTS[0],probed=True)
            raw,_=await routes.request(tid,'M03','vizier','votable_metadata',ENDPOINTS,'GET')
            assert b'SYNTHETIC' in raw and visited==['vizier.cds.unistra.fr']
            with pytest.raises(DomainError) as error:
                await app.http.request(tid,'M03','vizier','GET',ENDPOINTS[0])
            assert error.value.code=='SOURCE_ENDPOINT_COOLDOWN'
            assert len(visited)==1  # Historical unmanaged route remains guarded.
        finally:current_job.reset(token)
    asyncio.run(run())


def test_timed_managed_failure_still_stops_after_two_rounds(tmp_path):
    async def run():
        visited=[]
        async def handler(request):
            visited.append(request.url.host)
            raise httpx.ConnectTimeout('SYNTHETIC unavailable',request=request)
        app,tid,routes=setup(tmp_path,handler)
        token=current_job.set(catalog_job(app,tid))
        try:
            with pytest.raises(DomainError) as e:
                await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC'})
            assert e.value.code=='CATALOG_ENDPOINTS_UNAVAILABLE'
            assert len(visited)==6
            with pytest.raises(DomainError) as e:
                await routes.request(tid,'M03','vizier','votable_metadata',ENDPOINTS,'GET')
            assert e.value.code=='CATALOG_ENDPOINTS_UNAVAILABLE'
            assert len(visited)==6
        finally:current_job.reset(token)
    asyncio.run(run())


def test_timed_managed_rate_refusal_does_not_rotate_mirrors(tmp_path):
    async def run():
        visited=[]
        async def handler(request):
            visited.append(request.url.host)
            return httpx.Response(429,headers={'Retry-After':'60'})
        app,tid,routes=setup(tmp_path,handler)
        token=current_job.set(catalog_job(app,tid))
        try:
            state=routes.state(tid,'vizier','votable_metadata');state.update(preferred=ENDPOINTS[0],probed=True)
            with pytest.raises(DomainError) as e:
                await routes.request(tid,'M03','vizier','votable_metadata',ENDPOINTS,'GET')
            assert e.value.details['provider_status']==429
            assert visited==['vizier.cds.unistra.fr']
        finally:current_job.reset(token)
    asyncio.run(run())
