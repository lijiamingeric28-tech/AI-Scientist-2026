import asyncio
from uuid import uuid4

import httpx
import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.checkpoints import JobSteps
from astroquery_ai.runtime.errors import DomainError


def test_terminal_orphan_lease_cannot_block_next_query_after_recovery(tmp_path):
    app=Application(tmp_path)
    first=app.create('SYNTHETIC old terminal task',str(uuid4()))
    job=app.repository.claim_job('old-worker')
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn,first['task_id'],lifecycle='budget_exhausted')
    app.repository.recover()
    second=app.create('SYNTHETIC next query',str(uuid4()))
    claimed=app.repository.claim_job('new-worker')
    assert claimed['task_id']==second['task_id']
    with app.repository.read() as conn:
        old=conn.execute('SELECT status,reason FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()
        assert tuple(old)==('cancelled','terminal_task_recovery')


def test_terminal_task_drains_live_worker_without_erasing_attempts(tmp_path):
    from astroquery_ai.runtime.scheduler import Scheduler
    async def run():
        app=Application(tmp_path);task=app.create('SYNTHETIC terminal during execution',str(uuid4()))
        job=app.repository.claim_job('worker');scheduler=Scheduler(app)
        async def end_task(current):
            with app.repository.transaction() as conn:
                app.repository.mutate_task(conn,task['task_id'],lifecycle='budget_exhausted')
        scheduler.execute=end_task
        await scheduler.run_job(job)
        with app.repository.read() as conn:
            row=conn.execute('SELECT status,reason FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()
            assert tuple(row)==('cancelled','terminal_task_drain')
    asyncio.run(run())


def cancelled(app, text="SYNTHETIC maintenance case"):
    task = app.create(text, str(uuid4()))
    app.repository.control(task["task_id"], "cancel", str(uuid4()), task["revision"])
    return task["task_id"]


def test_cleanup_tombstone_blocks_late_writes_and_retains_shared_files(tmp_path):
    app = Application(tmp_path)
    a, b = cancelled(app), cancelled(app)
    artifact = app.artifacts.write(b"SYNTHETIC shared bytes", "application/pdf")
    with app.repository.transaction() as conn:
        for tid in (a, b):
            app.artifacts.register(conn, tid, "source", artifact)
    operation = str(uuid4())
    first = app.maintenance.cleanup(a, operation_id=operation, whole=True)
    assert first["items"][0]["status"] == "retained_shared"
    assert app.maintenance.cleanup(a, operation_id=operation, whole=True) == first
    assert app.artifacts.read_owned(b, artifact["artifact_id"])[1].exists()
    with pytest.raises(DomainError, match="任务已删除"):
        with app.repository.transaction() as conn:
            app.artifacts.register(conn, a, "late-owner", artifact)
    second = app.maintenance.cleanup(b, operation_id=str(uuid4()), whole=True)
    assert second["items"][0]["status"] == "deleted"
    assert not app.repository.list_tasks()
    with app.repository.read() as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] > 0


def test_recoverable_or_leased_resource_cannot_be_cleaned(tmp_path):
    app = Application(tmp_path)
    task = app.create("SYNTHETIC recoverable", str(uuid4()))
    with pytest.raises(DomainError) as exc:
        app.maintenance.cleanup(task["task_id"], operation_id=str(uuid4()), whole=True)
    assert exc.value.code == "TASK_RECOVERABLE"
    artifact = app.artifacts.write(b"SYNTHETIC lease", "application/pdf")
    with app.repository.transaction() as conn:
        app.artifacts.register(conn, task["task_id"], "source", artifact)
    lease = app.artifacts.lease(task["task_id"], artifact["artifact_id"])
    app.repository.control(task["task_id"], "cancel", str(uuid4()), task["revision"])
    with pytest.raises(DomainError) as exc:
        app.maintenance.cleanup(task["task_id"], operation_id=str(uuid4()), parts=["pdfs"])
    assert exc.value.code == "RESOURCE_LEASE_ACTIVE"
    app.artifacts.release(lease)
    assert (
        app.maintenance.cleanup(task["task_id"], operation_id=str(uuid4()), parts=["pdfs"])[
            "status"
        ]
        == "completed"
    )


def test_read_only_replay_creates_no_jobs_answers_or_paid_calls(tmp_path):
    app = Application(tmp_path)
    tid = cancelled(app)
    before = app.view(tid)
    operation = str(uuid4())
    created = app.history.replay(tid, 10, operation)
    assert app.history.replay(tid, 10, operation) == created
    replay = app.view(created["task_id"])
    assert replay["kind"] == "replay" and replay["pending"] is None and replay["reviews"] == []
    assert replay["replay"]["scientific_execution"] is False
    assert app.view(tid)["revision"] == before["revision"]
    assert app.view(tid)["core_event_cursor"] == before["core_event_cursor"]
    with app.repository.read() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM jobs WHERE task_id=?", (created["task_id"],)
            ).fetchone()[0]
            == 0
        )
    assert app.budget.summary()["committed_micros"] == 0
    with pytest.raises(DomainError) as exc:
        app.maintenance.cleanup(tid, operation_id=str(uuid4()), whole=True)
    assert exc.value.code == "REPLAY_SOURCE_REFERENCED"


def test_successful_http_step_is_reused_with_new_lease(tmp_path):
    async def run():
        app = Application(tmp_path)
        captures = []

        def handle(request):
            captures.append(request)
            return httpx.Response(200, content=b"SYNTHETIC response")

        app.http.transport = httpx.MockTransport(handle)
        task = app.create("SYNTHETIC checkpoint", str(uuid4()))
        first = app.repository.claim_job("first", lease_seconds=600)
        raw, meta = (
            await JobSteps(app)
            .http(first)
            .request(task["task_id"], "M01", "simbad", "GET", "https://example.test/data")
        )
        with app.repository.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET status='ready',lease_token=NULL WHERE job_id=?", (first["job_id"],)
            )
        resumed = app.repository.claim_job("second", lease_seconds=600)
        again, receipt = (
            await JobSteps(app)
            .http(resumed)
            .request(task["task_id"], "M01", "simbad", "GET", "https://example.test/data")
        )
        assert raw == again and meta == receipt
        assert len(captures) == 1
        with pytest.raises(DomainError):
            JobSteps(app).load(first, "old-lease-cannot-read-step")

    asyncio.run(run())


def test_each_redirect_is_accounted_and_secrets_do_not_cross_hosts(tmp_path):
    async def run():
        app = Application(tmp_path)
        captures = []

        def handle(request):
            captures.append(request)
            if request.url.host == "source.test":
                return httpx.Response(302, headers={"location": "https://document.test/paper"})
            return httpx.Response(200, content=b"SYNTHETIC PDF bytes")

        app.http.transport = httpx.MockTransport(handle)
        task = app.create("SYNTHETIC redirect", str(uuid4()))
        raw, metadata = await app.http.request(
            task["task_id"],
            "M01",
            "simbad",
            "GET",
            "https://source.test/",
            headers={"Authorization": "SYNTHETIC-NOT-A-REAL-SECRET"},
            max_redirects=2,
        )
        assert raw == b"SYNTHETIC PDF bytes" and len(metadata["redirect_chain"]) == 1
        assert "authorization" not in captures[1].headers
        with app.repository.read() as conn:
            assert conn.execute("SELECT count(*) FROM http_attempts").fetchone()[0] == 2

    asyncio.run(run())
