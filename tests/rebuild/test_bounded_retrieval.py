"""Synthetic limits/route contracts; these do not claim scientific accuracy."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY, ensure_window, remaining
from astroquery_ai.runtime.service_routes import ServiceRoutes
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.workflow.literature_service import LiteratureService, checked_property_query
from astroquery_ai.science.literature import FairReadLedger
from tests.rebuild.test_literature_selection import spec


def test_new_catalog_policy_has_quantity_not_deadline(tmp_path):
    repo = Repository(tmp_path/'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC finite table list')['task_id']
    with repo.transaction() as conn:
        ref = repo.put_object(conn, tid, 'confirmed_query', tid, 1, {'run_policy':deepcopy(NORMAL_RUN_POLICY)})
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open', query_ref=canonical(ref).decode())
        repo.enqueue(conn, tid, 'M03', 'catalog_discover', {})
    job = repo.claim_job('worker')
    with repo.transaction() as conn:
        assert ensure_window(repo, conn, job, now=1000) is None
        assert remaining(repo, conn, job, now=100000) is None
    assert NORMAL_RUN_POLICY['catalog']['maximum_tables'] == 20


def test_routes_failover_sticks_and_never_rotates_on_429():
    class HTTP:
        def __init__(self): self.calls = []
        async def request(self, tid, owner, service, method, endpoint, **kwargs):
            self.calls.append(endpoint)
            if endpoint == 'fr': raise DomainError('SOURCE_HTTP_TIMEOUT', 'SYNTHETIC')
            if endpoint == 'limited': raise DomainError('SOURCE_HTTP_ERROR', 'SYNTHETIC', provider_status=429, retry_after_seconds=2)
            return b'zero rows is a valid response', {'status':200}
    async def run():
        http = HTTP(); routes = ServiceRoutes(http)
        await routes.request('t', 'M03', 'vizier', 'data', ['fr','idia'], 'GET', timeout=20)
        assert http.calls == ['fr','idia']
        await routes.request('t', 'M03', 'vizier', 'data', ['fr','idia'], 'GET', timeout=20)
        assert http.calls[-1] == 'idia' and len(http.calls) == 3
        with pytest.raises(DomainError) as exc:
            await routes.request('t', 'M03', 'vizier', 'readme', ['limited','other'], 'GET')
        assert exc.value.details['provider_status'] == 429
        assert http.calls[-1] == 'limited'
    asyncio.run(run())


def test_probe_once_and_capabilities_are_separate():
    class HTTP:
        def __init__(self): self.calls=[]
        async def request(self, tid, owner, service, method, endpoint, **kwargs):
            self.calls.append(endpoint)
            return b'<VOTABLE></VOTABLE>', {'status':200}
    async def run():
        http=HTTP(); routes=ServiceRoutes(http)
        await routes.probe('t','M03','vizier','votable',['a','b','c'],{})
        await routes.probe('t','M03','vizier','votable',['a','b','c'],{})
        assert len(http.calls)==3
        assert routes.state('t','vizier','readme')['preferred'] is None
    asyncio.run(run())


def test_expression_accepts_combined_fields_but_not_citation_search():
    value=checked_property_query({'query':'(title:("star") OR body:("catalogue id")) AND abs:(temperature)', 'intent':'SYNTHETIC'})
    assert 'body:' in value and 'doctype:' in value
    with pytest.raises(DomainError):
        checked_property_query({'query':'citations(abs:("star"))', 'intent':'SYNTHETIC'})


def test_frozen_property_selection_has_no_failure_replacement():
    # Four exact properties can authorize 80 allocations, not a global 40.
    queues={f'p{p}':[f'w{p}-{i}' for i in range(20)] for p in range(4)}
    owners={w:[p] for p,ws in queues.items() for w in ws}
    ledger=FairReadLedger(list(queues), queues, owners, maximum_works=80, maximum_attempts=80)
    seen=[]
    while selection := ledger.select():
        seen.append(selection['work_id'])
        ledger.preflight_failed(selection['work_id'])
    assert len(seen)==80 and len(set(seen))==80
    assert all(sum(w in ws for w in seen)==20 for ws in queues.values())


def test_each_property_search_requests_40_once_and_resumes(tmp_path):
    repo=Repository(tmp_path/'runtime.sqlite3')
    tid=repo.create_task('SYNTHETIC per-property query')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open')
        repo.enqueue(conn,tid,'M04','literature_discover',{})
    job=repo.claim_job('worker',lease_seconds=600)
    class Artifacts:
        def write(self, raw, media):
            (tmp_path/'response.json').write_bytes(raw)
            return {'artifact_id':'synthetic-response'}
        def register(self,*args): pass
        def read_owned(self,*args):return None,tmp_path/'response.json'
    class Steps:
        def __init__(self):self.calls=[]
        async def model(self, execution, **kwargs):
            self.calls.append(('model',kwargs))
            return {'query':'abs:("star") AND body:(temperature)','intent':'SYNTHETIC'}, {'attempt_id':'synthetic'}
        def http(self, execution):return self
        async def request(self,*args,**kwargs):
            self.calls.append(('http',kwargs))
            return canonical({'response':{'docs':[], 'numFound':10000}}), {'status':200}
    steps=Steps(); app=SimpleNamespace(artifacts=Artifacts(),configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC'}))
    service=LiteratureService(SimpleNamespace(app=app,repo=repo,steps=steps,extractor=None))
    async def run():
        data=spec(); data['properties'][0]['definition']['family_id']='f'
        await service.property_query(job,data,data['properties'][0])
        await service.property_query(job,data,data['properties'][0])
        assert len(steps.calls)==2
        params=steps.calls[1][1]['params']
        assert params['rows']=='40' and params['start']=='0' and params['sort']=='score desc'
        assert 'reference' not in params['q'] and 'citation' not in params['q']
    asyncio.run(run())
