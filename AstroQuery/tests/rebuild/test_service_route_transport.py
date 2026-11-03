"""Normal route recovery reaches every mirror; no legacy shared retry cutoff."""
import asyncio
from collections import Counter
import httpx
import pytest
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.service_routes import ServiceRoutes

ENDPOINTS=['https://vizier.cds.unistra.fr/viz-bin/votable',
           'https://vizier.cfa.harvard.edu/viz-bin/votable',
           'https://vizier.idia.ac.za/viz-bin/votable']


def setup(tmp_path,handler):
    app=Application(tmp_path);tid=app.repository.create_task('SYNTHETIC mirror transport',kind='validation')['task_id']
    with app.repository.transaction() as c:
        app.repository.put_object(c,tid,'calibration_scope',tid,1,
            {'allowed_owners':['M03'],'allowed_services':['vizier'],'max_requests':40})
    app.http.transport=httpx.MockTransport(handler)
    return app,tid,ServiceRoutes(app.http)


def test_second_round_success_is_not_discarded_by_other_mirrors_shared_count(tmp_path):
    async def run():
        counts=Counter()
        async def handler(request):
            host=request.url.host;counts[host]+=1
            if host!='vizier.idia.ac.za' or counts[host]==1:
                raise httpx.ConnectTimeout('SYNTHETIC transient/unavailable',request=request)
            return httpx.Response(200,content=b'<VOTABLE/>')
        app,tid,routes=setup(tmp_path,handler)
        await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC','-out.max':'0'})
        assert routes.state(tid,'vizier','votable_metadata')['preferred']==ENDPOINTS[2]
        assert list(sorted(counts.values()))==[2,2,2]
        await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC','-out.max':'0'})
        assert sum(counts.values())==6
        raw,metadata=await routes.request(tid,'M03','vizier','votable_metadata',ENDPOINTS,'GET',params={'-words':'different actual query'})
        assert raw==b'<VOTABLE/>' and metadata['selected_route']==ENDPOINTS[2]
        assert sum(counts.values())==7
    asyncio.run(run())


def test_all_mirrors_fail_two_rounds_then_cooldown_and_later_recover(tmp_path):
    async def run():
        calls=[];recovered=False
        async def handler(request):
            calls.append(request.url.host)
            if not recovered:raise httpx.ConnectTimeout('SYNTHETIC outage',request=request)
            return httpx.Response(200,content=b'<VOTABLE/>')
        app,tid,routes=setup(tmp_path,handler)
        async def probe():return await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC'})
        with pytest.raises(DomainError) as exc:await probe()
        assert exc.value.code=='CATALOG_ENDPOINTS_UNAVAILABLE' and len(calls)==6
        with pytest.raises(DomainError):await probe()
        assert len(calls)==6
        # Model a real cooldown expiry, without sleeping for a minute.
        routes.state(tid,'vizier','votable_metadata')['unavailable_until']=0;recovered=True
        await probe()
        assert len(calls)==9 and routes.state(tid,'vizier','votable_metadata')['preferred'] in ENDPOINTS
    asyncio.run(run())


def test_redirecting_mirror_does_not_cancel_a_successful_sibling_probe(tmp_path):
    async def run():
        calls=Counter()
        async def handler(request):
            calls[request.url.host]+=1
            if request.url.host=='vizier.idia.ac.za':
                return httpx.Response(302,headers={'location':'https://vizier.cds.unistra.fr/viz-bin/votable'})
            if request.url.host=='vizier.cds.unistra.fr':
                raise httpx.ConnectTimeout('SYNTHETIC unreachable primary',request=request)
            await asyncio.sleep(.02)
            return httpx.Response(200,content=b'<VOTABLE/>')
        app,tid,routes=setup(tmp_path,handler)
        await routes.probe(tid,'M03','vizier','votable_metadata',ENDPOINTS,{'-source':'SYNTHETIC'})
        state=routes.state(tid,'vizier','votable_metadata')
        assert state['preferred']==ENDPOINTS[1] and calls['vizier.cfa.harvard.edu']==1
        assert any(f['reason']=='SOURCE_REDIRECT_LIMIT' for f in state['probe_failures'])
    asyncio.run(run())


@pytest.mark.parametrize('response_state,expected',[
    ('failed','catalog_discovery_access_incomplete'),
    ('complete_for_expression','screened_no_relevant_tables')])
def test_discovery_coverage_does_not_turn_access_failure_into_scientific_absence(tmp_path,response_state,expected):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
    from astroquery_ai.science.catalog.selection import replenish
    repo=Repository(tmp_path/'runtime.sqlite3');tid=repo.create_task('SYNTHETIC discovery coverage')['task_id']
    with repo.transaction() as c:
        ref=repo.put_object(c,tid,'confirmed_query',tid,1,{'run_policy':CONSOLIDATION_RUN_POLICY})
        repo.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        repo.put_object(c,tid,'catalog_pool',tid,1,{'revision':1,'candidates':[],'dispatched':[],
            'closed':False,'property_order':[],'discovered_tables':[],'checked_tables':[],'discovered_resources':[]})
        repo.put_object(c,tid,'catalog_response','response',1,{'expression':'SYNTHETIC','coverage_state':response_state,
            'reason':'SOURCE_HTTP_TIMEOUT' if response_state=='failed' else None})
        replenish(repo,c,tid)
        coverage=repo.objects(c,tid,'coverage')[0]
        assert coverage['reason']==expected
        assert bool(coverage['discovery_access_failures'])==(response_state=='failed')
