"""Synthetic clock/fairness/dispatch boundaries, never scientific accuracy."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY, ensure_window, guard, user_pause, sweep_ready, current_job, catalog_window, elapsed
# Historical six-hundred-second task compatibility; the normal strategy no
# longer has a module clock. Retain all clock assertions on an explicit frozen
# historical fixture, not on the newly published default (spec section 1).
NORMAL_RUN_POLICY = deepcopy(NORMAL_RUN_POLICY)
NORMAL_RUN_POLICY['catalog'].update(discovery_seconds=120,stop_dispatch_seconds=540,end_seconds=600)

from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.catalog.selection import fair_candidates, checked_ranking


def controlled(repo):
    tid = repo.create_task('SYNTHETIC catalog window')['task_id']
    with repo.transaction() as conn:
        spec = {'run_policy': deepcopy(NORMAL_RUN_POLICY), 'dependencies': [], 'registry_release': {'id': 'synthetic'}, 'properties': []}
        spec['spec_hash'] = digest(spec)
        ref = repo.put_object(conn, tid, 'confirmed_query', tid, 1, spec)
        repo.mutate_task(conn, tid, lifecycle='running', science_state='open', query_ref=canonical(ref).decode())
        for name in ['catalog_hints', 'catalog_discovery', 'synthetic_hold']:
            repo.producer(conn, tid, name)
        jid = repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': 'synthetic'})
    job = repo.claim_job('worker')
    return tid, job


def test_one_clock_dispatch_commit_pause_restart(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid, job = controlled(repo)
    with repo.transaction() as conn:
        window = ensure_window(repo, conn, job, now=1000)
        assert ensure_window(repo, conn, job, now=1300)['started_at'] == 1000
        with pytest.raises(DomainError, match='停止派发'):
            guard(repo, conn, job, dispatch=True, now=1540)
        assert guard(repo, conn, job, now=1599) == 1
        with pytest.raises(DomainError, match='窗口'):
            guard(repo, conn, job, now=1600)
        user_pause(repo, conn, tid, 'pause', now=1200)
        user_pause(repo, conn, tid, 'continue', now=1800)
        assert guard(repo, conn, job, now=1800) == 400
        assert guard(repo, conn, job, now=2199) == 1
    reopened = Repository(tmp_path / 'runtime.sqlite3')
    with reopened.read() as conn:
        with pytest.raises(DomainError):
            guard(reopened, conn, job, now=2200)


def test_sweep_closes_future_backoff_without_touching_attachment(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid, job = controlled(repo)
    with repo.transaction() as conn:
        ensure_window(repo, conn, job, now=1000)
        repo.finish_job(conn, job)
        pending = repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': 'late'})
        attachment = repo.enqueue(conn, tid, 'M03', 'attachment_extract', {'table_id': 'official'})
        repo.put_object(conn, tid, 'dispatch_wait', pending, 1, {'eligible_at': 99999999999})
        assert sweep_ready(repo, conn, task_id=tid, now=1540) == {tid}
        states = dict(conn.execute('SELECT job_id,status FROM jobs WHERE task_id=?', (tid,)))
        assert states[pending] == 'not_run' and states[attachment] == 'ready'
        assert repo.objects(conn, tid, 'coverage')[0]['outcome'] == 'not_checked_time_control'
        window = catalog_window(repo, conn, tid)
        assert window['closed'] and window['finished_at'] == 1540
        assert elapsed(window) == 540


def test_fair_waves_cover_properties_and_do_not_use_return_order():
    rows = [{'node_id': f'p0-{n}', 'property_ids': ['p0'], 'priority': 3, 'source_group': 'same'} for n in range(30)]
    rows += [{'node_id': 'p1', 'property_ids': ['p1'], 'priority': 2, 'source_group': 'other'},
             {'node_id': 'p2', 'property_ids': ['p2'], 'priority': 2, 'source_group': 'third'}]
    first = fair_candidates(rows, ['p0', 'p1', 'p2'])
    assert len(first) == 8 and {'p1', 'p2'} <= {r['node_id'] for r in first}
    assert first == fair_candidates(list(reversed(rows)), ['p0', 'p1', 'p2'])
    second = fair_candidates(rows, ['p0', 'p1', 'p2'], selected=first, maximum=8)
    assert not {r['node_id'] for r in first}.intersection(r['node_id'] for r in second)


def test_selection_cannot_invent_table_or_scope_or_evidence():
    spec = {'properties': [{'property_id': 'p'}]}
    native = [{'node_id': 'table', 'source_group': 'catalog', 'description': 'Synthetic physical quantity', 'columns': []}]
    item = {'node_id': 'table', 'property_ids': ['p'], 'priority': 3, 'evidence_quote': 'physical quantity'}
    assert checked_ranking({'candidates': [item]}, native, spec)[0]['node_id'] == 'table'
    for change in [{'node_id': 'invented'}, {'property_ids': ['other']}, {'evidence_quote': 'not in source'}]:
        with pytest.raises(DomainError):
            checked_ranking({'candidates': [{**item, **change}]}, native, spec)
    checked = checked_ranking({'candidates': [{**item, 'object_hint':'a plausible target claim outside source'}]}, native, spec)
    assert checked[0]['object_hint'] is None
    assert checked[0]['unverified_object_hint'] == 'a plausible target claim outside source'


def test_resumed_failed_discovery_expiry_preserves_already_closed_producer(tmp_path):
    repo=Repository(tmp_path/'runtime.sqlite3')
    tid,job=controlled(repo)
    job['kind']='catalog_discover'
    with repo.transaction() as conn:
        conn.execute("UPDATE jobs SET kind='catalog_discover',status='ready' WHERE job_id=?",(job['job_id'],))
        ensure_window(repo,conn,job,now=100)
        for name in ['catalog_hints','catalog_discovery']:
            repo.producer(conn,tid,name,close_reason='original_failure',watermark=2)
        sweep_ready(repo,conn,task_id=tid,now=641)
        assert conn.execute('SELECT status FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]=='not_run'
        assert conn.execute("SELECT close_reason FROM producers WHERE task_id=? AND producer_id='catalog_hints'",(tid,)).fetchone()[0]=='original_failure'


def test_resumed_catalog_closure_keeps_both_coverage_versions(tmp_path, monkeypatch):
    from astroquery_ai.runtime.run_policy import save_window
    from astroquery_ai.science.catalog.selection import replenish
    repo=Repository(tmp_path/'runtime.sqlite3');tid,job=controlled(repo)
    monkeypatch.setattr('astroquery_ai.runtime.run_policy.time.time',lambda:1200)
    with repo.transaction() as conn:
        ensure_window(repo,conn,job,now=1000);repo.finish_job(conn,job)
        pool={'revision':1,'closed':False,'dispatched':[],'candidates':[],
              'property_order':[],'discovered_resources':[],'discovered_tables':[],'checked_tables':[]}
        repo.put_object(conn,tid,'catalog_pool',tid,1,pool);replenish(repo,conn,tid)
        window=catalog_window(repo,conn,tid)
        save_window(repo,conn,tid,{**window,'closed':False,'finished_at':None})
        pool=repo.objects(conn,tid,'catalog_pool')[0]
        repo.put_object(conn,tid,'catalog_pool',tid,pool['revision']+1,{**pool,'closed':False,'revision':pool['revision']+1})
        monkeypatch.setattr('astroquery_ai.runtime.run_policy.time.time',lambda:1540)
        replenish(repo,conn,tid)
        assert conn.execute("SELECT count(*) FROM objects WHERE task_id=? AND kind='coverage' AND object_id='catalog-controlled-selection'",(tid,)).fetchone()[0]==2
        assert repo.objects(conn,tid,'coverage')[0]['reason']=='catalog_time_limit'


def test_expiry_reconciliation_error_is_visible_without_killing_workers(tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.runtime.scheduler import Scheduler
    repo=Repository(tmp_path/'runtime.sqlite3');tid,job=controlled(repo)
    async def fail(_):raise DomainError('IMMUTABLE_VERSION','SYNTHETIC closure fault')
    scheduler=object.__new__(Scheduler);scheduler.repository=repo;scheduler.pipeline=SimpleNamespace(advance=fail)
    asyncio.run(scheduler.advance_after_expiry(tid))
    assert repo.get_task(tid)['lifecycle']=='interrupted'
    with repo.read() as conn:
        assert conn.execute('SELECT status FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]=='running'


def test_endpoint_failure_cools_but_empty_success_does_not(tmp_path):
    from astroquery_ai.runtime.http import ScientificHTTP
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid, job = controlled(repo)
    with repo.transaction() as conn:
        ensure_window(repo, conn, job)
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(503 if request.url.path.endswith('broken') else 200, content=b'empty but successful')
    http = ScientificHTTP(repo, transport=httpx.MockTransport(response))
    async def run():
        token = current_job.set(job)
        try:
            with pytest.raises(DomainError):
                await http.request(tid, 'M03', 'vizier', 'GET', 'https://vizier.idia.ac.za/broken')
            with pytest.raises(DomainError) as caught:
                await http.request(tid, 'M03', 'vizier', 'GET', 'https://vizier.idia.ac.za/broken')
            assert caught.value.code == 'SOURCE_ENDPOINT_COOLDOWN'
            for _ in range(2):
                await http.request(tid, 'M03', 'vizier', 'GET', 'https://vizier.idia.ac.za/empty')
        finally:
            current_job.reset(token)
    asyncio.run(run())
    assert len(calls) == 3


def test_late_scientific_commit_is_rejected_and_keeps_saved_evidence(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid, job = controlled(repo)
    with repo.transaction() as conn:
        ensure_window(repo, conn, job, now=1000)
        repo.put_object(conn, tid, 'evidence', 'early', 1, {'raw': 'SYNTHETIC original'})
    monkeypatch.setattr('time.time', lambda: 1600)
    with pytest.raises(DomainError) as error:
        with repo.transaction() as conn:
            repo.validate_lease(conn, job)
            repo.put_object(conn, tid, 'measurement', 'late', 1, {'value': 'unaccepted'})
    assert error.value.code == 'CATALOG_WINDOW_EXPIRED'
    with repo.read() as conn:
        assert not repo.objects(conn, tid, 'measurement')
        assert repo.object(conn, tid, 'evidence', 'early')['raw'] == 'SYNTHETIC original'


def test_inflight_identical_gets_share_owned_response(tmp_path):
    from tests.rebuild.scenario import application
    from astroquery_ai.runtime.checkpoints import JobSteps
    app = application(tmp_path)
    tid, job = controlled(app.repository)
    with app.repository.transaction() as conn:
        ensure_window(app.repository, conn, job)
    calls = []
    async def handle(request):
        calls.append(request)
        await asyncio.sleep(.02)
        return httpx.Response(200, content=b'SYNTHETIC metadata')
    app.http.transport = httpx.MockTransport(handle)
    async def run():
        token = current_job.set(job)
        try:
            result = await asyncio.gather(*(JobSteps(app).http(job).request(tid, 'M03', 'vizier', 'GET',
                'https://vizier.idia.ac.za/viz-bin/votable', params={'-source': 'SYNTHETIC'}) for _ in range(3)))
            assert all(r[0] == b'SYNTHETIC metadata' for r in result)
        finally:
            current_job.reset(token)
    asyncio.run(run())
    assert len(calls) == 1
