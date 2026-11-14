"""Real local queue/state transitions with injected failures, no provider calls."""
import asyncio
from uuid import uuid4

import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler


def queue(app, kind='paper_batch'):
    task = app.repository.create_task('SYNTHETIC failure isolation')
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, task['task_id'], lifecycle='queued')
        app.repository.enqueue(conn, task['task_id'], 'M06', kind, {})
    return task['task_id']


@pytest.mark.parametrize('failure_at', ['advance', 'failure_handler'])
def test_secondary_failure_interrupts_own_task_and_worker_serves_next(tmp_path, monkeypatch, failure_at):
    async def run():
        app = Application(tmp_path)
        bad, good = queue(app), queue(app)
        scheduler = Scheduler(app)
        finished = asyncio.Event()

        async def execute(job):
            if job['task_id'] == bad:
                raise ValueError('synthetic first failure')
            with app.repository.transaction() as conn:
                app.repository.finish_job(conn, job)
                app.repository.mutate_task(conn, good, lifecycle='completed')
            finished.set()

        async def advance(tid):
            if tid == bad:
                raise KeyError('synthetic orchestration failure')

        monkeypatch.setattr(scheduler, 'execute', execute)
        monkeypatch.setattr(scheduler.pipeline, 'advance', advance)
        if failure_at == 'failure_handler':
            def broken(*args):
                raise KeyError('synthetic failure-receipt bug')
            monkeypatch.setattr(app.failures, 'handle', broken)
        await scheduler.start()
        try:
            await asyncio.wait_for(finished.wait(), 3)
            assert not scheduler.worker.done()
            state = app.repository.get_task(bad)
            assert state['lifecycle'] == 'interrupted' and state['resume_required']
            assert app.repository.get_task(good)['lifecycle'] == 'completed'
            events = app.repository.events(bad)
            assert any(e['kind'] == 'orchestration_interrupted' for e in events)
        finally:
            await scheduler.stop()
    asyncio.run(run())


@pytest.mark.parametrize('cancel_owner', [False, True])
def test_parallel_children_finish_cleanup_before_owner_failure_returns(cancel_owner):
    from astroquery_ai.runtime.async_scope import gather_scoped

    async def run():
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def slow():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        async def fail():
            await entered.wait()
            raise DomainError('SYNTHETIC_PARALLEL_FAILURE', 'synthetic failure')

        operation = asyncio.create_task(gather_scoped(slow(), slow() if cancel_owner else fail()))
        await entered.wait()
        if cancel_owner:
            operation.cancel()
        with pytest.raises(asyncio.CancelledError if cancel_owner else DomainError):
            await operation
        assert cleaned.is_set()
    asyncio.run(run())


def test_actual_metadata_coordinator_drains_sibling_on_failure(monkeypatch):
    from types import SimpleNamespace
    from astroquery_ai.science import metadata_preparation

    async def run():
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def fetch(service, job, spec, binding, batch):
            if binding['property_id'] == 'fail':
                await entered.wait()
                raise DomainError('SOURCE_HTTP_TIMEOUT', 'synthetic')
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        monkeypatch.setattr(metadata_preparation, 'fetch_batch', fetch)
        with pytest.raises(DomainError):
            await metadata_preparation.discover(SimpleNamespace(), {'task_id': 'SYNTHETIC'},
                {'properties': [{'property_id': 'fail'}, {'property_id': 'slow'}]})
        assert cleaned.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('deferred', [False, True])
def test_pause_finishes_when_last_inflight_request_fails_and_can_resume(tmp_path, deferred):
    from astroquery_ai.runtime.throughput import DispatchDeferred
    app = Application(tmp_path)
    tid = queue(app)
    scheduler = Scheduler(app)
    job = app.repository.claim_job(scheduler.owner_id)
    state = app.repository.get_task(tid)
    paused = app.repository.control(tid, 'pause', str(uuid4()), state['revision'])
    assert paused['lifecycle'] == 'pausing'
    scheduler.fail(job, DispatchDeferred('model', .05) if deferred else DomainError('PROVIDER_TIMEOUT', 'synthetic timeout'))
    state = app.repository.get_task(tid)
    assert state['lifecycle'] == 'paused'
    app.repository.control(tid, 'continue', str(uuid4()), state['revision'])
    # No confirmed request here: continue returns the editable draft state.
    assert app.repository.get_task(tid)['lifecycle'] == 'waiting_input'
    with app.repository.read() as conn:
        assert conn.execute('SELECT status FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()[0] == 'ready'


def test_material_coordinator_exhaustion_is_visible_not_an_idle_open_query(tmp_path):
    app = Application(tmp_path)
    tid = queue(app, 'material_prepare')
    scheduler = Scheduler(app)
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, tid, 'material_preparation', tid, 1,
                                  {'revision': 1, 'closed': False, 'pools': {}})
        app.repository.producer(conn, tid, 'selections')
    for attempt in range(3):
        job = app.repository.claim_job(scheduler.owner_id)
        assert job is not None
        scheduler.fail(job, DomainError('MATERIAL_ACQUISITION_JOB_FAILED', 'synthetic unresolved acquisition'))
    state = app.repository.get_task(tid)
    assert state['lifecycle'] == 'interrupted' and state['resume_required']
    assert app.repository.claim_job(scheduler.owner_id) is None
    with app.repository.read() as conn:
        assert conn.execute('SELECT status FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()[0] == 'ready'
        assert app.repository.objects(conn, tid, 'material_preparation')[0]['closed'] is False
        assert not app.repository.objects(conn, tid, 'delivery')


def test_heartbeat_failure_cancels_inflight_operation_before_return(tmp_path, monkeypatch):
    async def run():
        app = Application(tmp_path)
        tid = queue(app)
        scheduler = Scheduler(app)
        job = app.repository.claim_job(scheduler.owner_id)
        started, stopped = asyncio.Event(), asyncio.Event()
        original_wait = asyncio.wait_for

        async def execute(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def short_wait(awaitable, timeout):
            return await original_wait(awaitable, min(timeout, .02))

        def renew(_):
            raise DomainError('STALE_LEASE', 'synthetic lost lease')

        async def advance(_):
            return None

        monkeypatch.setattr(scheduler, 'execute', execute)
        monkeypatch.setattr(scheduler.pipeline, 'advance', advance)
        monkeypatch.setattr(app.repository, 'renew', renew)
        monkeypatch.setattr(asyncio, 'wait_for', short_wait)
        await scheduler.run_job(job)
        assert started.is_set() and stopped.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['catalog_discover', 'catalog_extract', 'literature_discover',
    'material_prepare', 'quality_verify', 'normalize', 'compare_results', 'finalize'])
def test_normal_query_fault_matrix_preserves_closure_and_recovery(tmp_path, monkeypatch, kind):
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
    from tests.rebuild import scenario

    async def run():
        app = scenario.application(tmp_path)
        ordinary = app.models.json
        faults = 0
        repaired = False

        async def model(**kw):
            if kw['profile'].version == 'unified-catalog-quality-2':
                body = loads(kw['messages'][0]['content'])
                return {'items': [{'item_id': row['item_id'], 'subject': 'target',
                    'quantity_relation': 'same', 'reported_quantity': 'SYNTHETIC whole length',
                    'subject_scale': 'whole target', 'result_role': 'reported_result',
                    'native_representation': 'linear', 'value_match': 'exact', 'unit_match': 'exact',
                    'errors_match': 'not_reported', 'evidence_columns': ['Length'],
                    'checked_ids': list(body['source_materials'])[:1], 'caution_ids': [],
                    'review_issue': None, 'reason': 'SYNTHETIC evidence checked'} for row in body['items']]}, {'attempt_id': 'synthetic-QC'}
            return await ordinary(**kw)

        def setup(scheduler):
            handler = scheduler.handlers[kind]

            async def fail_job(job):
                nonlocal faults
                if not repaired:
                    faults += 1
                    raise DomainError('PROVIDER_TIMEOUT', 'SYNTHETIC persistent stage failure')
                await handler(job)
            scheduler.handlers[kind] = fail_job

        async def drive(application, scheduler):
            for _ in range(100):
                job = application.repository.claim_job(scheduler.owner_id, lease_seconds=600)
                if job is None:
                    return
                await scheduler.run_job(job)
            raise AssertionError('Unbounded job requeue after injected failure')

        app.models.json = model
        monkeypatch.setattr(scenario, 'run_until_wait', drive)
        state, scheduler = await scenario.confirmed_case(app, setup_scheduler=setup,
                                                        run_policy=CONSOLIDATION_RUN_POLICY)
        assert 1 <= faults <= 3
        tid = state['task_id']
        if kind in {'material_prepare', 'finalize'}:
            assert state['lifecycle'] == 'interrupted' and state['resume_required']
            assert not state['delivery_ref']
            repaired = True
            app.repository.control(tid, 'continue', str(uuid4()), state['revision'])
            await drive(app, scheduler)
            state = app.view(tid)
        assert state['lifecycle'] == 'completed' and state['science_state'] == 'sealed'
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, tid)
            assert not conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN "
                                    "('ready','running','waiting_dependency','awaiting_review')", (tid,)).fetchone()
            assert not conn.execute("SELECT 1 FROM producers WHERE task_id=? AND state='open'", (tid,)).fetchone()
            if kind not in {'material_prepare', 'finalize'}:
                assert any(x.get('reason') == 'PROVIDER_TIMEOUT'
                           for x in app.repository.objects(conn, tid, 'coverage'))
                assert delivery['status'] == 'partial'
            if kind not in {'catalog_discover', 'catalog_extract', 'quality_verify'}:
                assert len(delivery['measurements']) == 1
                assert delivery['measurements'][0]['value']['value'] == '0'
        for fmt in ('json', 'json_wide', 'csv_long', 'csv_wide', 'package'):
            result = app.delivery.export(tid, {'operation_id': str(uuid4()), 'task_id': tid,
                'delivery_id': delivery['delivery_id'], 'expected_delivery_revision': 1,
                'selection': {'mode': 'all', 'measurement_ids': []}, 'format': fmt, 'export_schema_version': 1})
            assert result['snapshot_ref'] == delivery['snapshot_ref']
        assert app.budget.summary()['committed_micros'] == 0
    asyncio.run(run())
