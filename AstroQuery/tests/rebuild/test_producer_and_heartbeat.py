import asyncio

from astroquery_ai.runtime.repository import Repository
from tests.rebuild.scenario import application, confirmed_case, run_until_wait


def test_postcommit_heartbeat_does_not_interrupt_a_successful_job(tmp_path):
    repo = Repository(tmp_path / 'SYNTHETIC.sqlite3')
    tid = repo.create_task('SYNTHETIC heartbeat race')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='queued', science_state='open')
        repo.enqueue(conn, tid, 'M13', 'reconcile', {})
    job = repo.claim_job('SYNTHETIC worker')
    with repo.transaction() as conn:
        repo.finish_job(conn, job)
    before = repo.get_task(tid)
    assert repo.renew(job) is False
    assert repo.get_task(tid) == before


def test_open_producer_prevents_premature_finalize_and_closing_it_continues_normally(tmp_path):
    async def run():
        app = application(tmp_path)
        create = app.create

        def create_with_pending_producer(*args, **kwargs):
            result = create(*args, **kwargs)
            with app.repository.transaction() as conn:
                app.repository.producer(conn, result['task_id'], 'SYNTHETIC independent owner')
            return result

        app.create = create_with_pending_producer
        state, scheduler = await confirmed_case(app)
        tid = state['task_id']
        assert state['science_state'] == 'open'
        with app.repository.transaction() as conn:
            assert not conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='finalize'", (tid,)).fetchone()
            app.repository.producer(conn, tid, 'SYNTHETIC independent owner', close_reason='SYNTHETIC work ended')
        await scheduler.pipeline.advance(tid)
        await run_until_wait(app, scheduler)
        assert app.view(tid)['science_state'] == 'sealed'
        assert app.view(tid)['lifecycle'] == 'completed'

    asyncio.run(run())
