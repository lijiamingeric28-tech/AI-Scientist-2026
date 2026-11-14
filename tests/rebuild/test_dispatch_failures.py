import asyncio
from uuid import uuid4

import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.budget import Budget
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.reviews import ReviewAnswer
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.scenario import application, confirmed_case, run_until_wait


def test_local_attempt_limit_keeps_independent_jobs_runnable(tmp_path):
    app = Application(tmp_path)
    task = app.create("SYNTHETIC local failure scope", str(uuid4()))
    with app.repository.transaction() as conn:
        conn.execute("UPDATE jobs SET status='not_run' WHERE task_id=?", (task["task_id"],))
        app.repository.enqueue(
            conn, task["task_id"], "M03", "catalog_extract", {"table_id": "SYNTHETIC/A"}
        )
        app.repository.enqueue(
            conn, task["task_id"], "M03", "catalog_extract", {"table_id": "SYNTHETIC/B"}
        )
    scheduler = Scheduler(app)
    job = app.repository.claim_job(scheduler.owner_id)
    scheduler.fail(job, DomainError("ATTEMPT_LIMIT", "SYNTHETIC exhausted item"))
    assert app.repository.get_task(task["task_id"])["lifecycle"] != "budget_exhausted"
    assert app.repository.claim_job(scheduler.owner_id)["payload"]["table_id"] == "SYNTHETIC/B"
    assert app.budget.summary()["committed_micros"] == 0


def test_failed_insights_finish_with_facts_and_same_delivery(tmp_path, monkeypatch):
    from copy import deepcopy
    from astroquery_ai.runtime import run_policy
    monkeypatch.setattr(run_policy, 'request_policy', lambda _, preferences=None: deepcopy(run_policy.LEGACY_RUN_POLICY))
    async def run():
        app = application(tmp_path)
        scheduler = Scheduler(app)
        task = app.create("SYNTHETIC_AQ 测试长度", str(uuid4()))
        await run_until_wait(app, scheduler)
        state = app.view(task["task_id"])
        app.draft_action(
            task["task_id"],
            {
                "protocol_version": 2,
                "operation_id": str(uuid4()),
                "expected_revision": state["revision"],
                "question_id": state["pending"]["question_id"],
                "action": {
                    "type": "confirm",
                    "preview_hash": state["pending"]["preview"]["preview_hash"],
                },
            },
        )
        for _ in range(60):
            job = app.repository.claim_job(scheduler.owner_id, lease_seconds=600)
            assert job is not None
            if job["kind"] == "insights":
                break
            await scheduler.dispatch(job)
        else:
            raise AssertionError("insight job missing")
        before = app.view(task["task_id"])["delivery_ref"]
        scheduler.fail(job, KeyError("SYNTHETIC faulty insight adapter"))
        state = app.view(task["task_id"])
        assert state["lifecycle"] == "completed" and state["delivery_ref"] == before
        with app.repository.read() as conn:
            report = app.repository.object(
                conn, task["task_id"], "insight", state["insight_ref"]["id"]
            )
            assert (
                report["status"] == "partial" and report["facts"][0]["source_value"]["value"] == "0"
            )
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())


def test_global_budget_closes_accepted_unapplied_answers_and_publishes_partial(tmp_path):
    async def run():
        app = application(tmp_path)
        state, scheduler = await confirmed_case(app, ambiguous=True)
        with app.repository.transaction() as conn:
            app.repository.mutate_task(conn, state["task_id"], lifecycle="queued")
            app.repository.enqueue(
                conn,
                state["task_id"],
                "M03",
                "catalog_extract",
                {"table_id": "SYNTHETIC independent remaining source"},
            )
        inflight = app.repository.claim_job(scheduler.owner_id)
        review = state["reviews"][0]
        app.reviews.answer(
            ReviewAnswer(
                task_id=state["task_id"],
                review_id=review["review_id"],
                review_revision=review["revision"],
                basis_hash=review["basis_hash"],
                client_request_id=str(uuid4()),
                action="unable",
                reason="SYNTHETIC pending answer",
            )
        )
        scheduler.fail(inflight, DomainError("CAMPAIGN_BUDGET_EXHAUSTED", "SYNTHETIC global cap"))
        final = app.view(state["task_id"])
        assert final["lifecycle"] == "budget_exhausted"
        assert final["reviews"][0]["status"] == "closed_unapplied"
        assert final["delivery_ref"] and final["science_state"] == "sealed"
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, state["task_id"])
            assert delivery["status"] == "partial" and delivery["measurements"] == []

    asyncio.run(run())


def test_dispatch_guard_failure_releases_known_unsent_reservation(tmp_path):
    repo = Repository(tmp_path / "budget.sqlite3")
    task = repo.create_task("SYNTHETIC dispatch refusal")
    budget = Budget(repo)
    attempt = budget.reserve(
        task_id=task["task_id"],
        owner="M01",
        model="qwen3.8-flash",
        root_id="guard",
        request={},
        input_bound=1000,
        output_bound=1000,
        smoke=True,
    )

    def refuse(conn, row):
        raise DomainError("READ_GRANT_MISSING", "SYNTHETIC no dispatch")

    with pytest.raises(DomainError):
        budget.dispatch(attempt["attempt_id"], authorize=refuse)
    assert budget.summary()["committed_micros"] == 0
    with repo.read() as conn:
        assert conn.execute("SELECT status FROM attempts").fetchone()[0] == "not_dispatched"


def test_distinct_work_operations_have_no_cumulative_clock_quota(tmp_path):
    repo = Repository(tmp_path / "scope.sqlite3")
    task = repo.create_task("SYNTHETIC finite work scope")
    with repo.transaction() as conn:
        spec = {
            "spec_id": "SYNTHETIC frozen",
            "dependencies": [],
            "registry_release": {"id": "SYNTHETIC release"},
        }
        ref = repo.put_object(conn, task["task_id"], "confirmed_query", spec["spec_id"], 1, spec)
        repo.mutate_task(
            conn,
            task["task_id"],
            query_ref=canonical(ref).decode(),
            lifecycle="queued",
            science_state="open",
        )
        repo.enqueue(conn, task["task_id"], "M06", "paper_batch", {"work_id": "SYNTHETIC work"})
    job = repo.claim_job("SYNTHETIC worker", lease_seconds=600)
    budget = Budget(repo)
    for i in range(5):
        attempt = budget.reserve(
            task_id=task["task_id"],
            owner="M06",
            model="qwen3.7-plus",
            root_id="different-root-" + str(i),
            request={"synthetic": i},
            input_bound=1000,
            output_bound=1000,
            smoke=True,
            purpose="production",
            profile_state="validated",
            job=job,
            wall_bound_seconds=480,
        )
        budget.dispatch(attempt["attempt_id"])
        budget.settle(attempt["attempt_id"], input_tokens=None, output_tokens=None, receipt={})
    attempt = budget.reserve(
            task_id=task["task_id"],
            owner="M06",
            model="qwen3.7-plus",
            root_id="cannot-reset-scope",
            request={},
            input_bound=1000,
            output_bound=1000,
            smoke=True,
            purpose="production",
            profile_state="validated",
            job=job,
        )
    assert attempt['status'] == 'reserved'
    assert budget.summary()["unknown_count"] == 5


def test_budget_publication_waits_for_sibling_worker_to_drain(tmp_path, monkeypatch):
    async def run():
        app = application(tmp_path)
        state, scheduler = await confirmed_case(app, ambiguous=True)
        tid = state["task_id"]
        with app.repository.transaction() as conn:
            app.repository.mutate_task(conn, tid, lifecycle="queued")
            for suffix in ("A", "B"):
                app.repository.enqueue(conn, tid, "M03", "catalog_extract", {"table_id": "SYNTHETIC/" + suffix})
        failure = app.repository.claim_job(scheduler.owner_id)
        sibling = app.repository.claim_job(scheduler.owner_id)
        assert sibling is not None
        scheduler.fail(failure, DomainError("CAMPAIGN_BUDGET_EXHAUSTED", "SYNTHETIC global cap"))
        before = app.view(tid)
        assert before["lifecycle"] == "budget_exhausted"
        assert before["delivery_ref"] is None

        async def already_stopped(job):
            raise DomainError("DISPATCH_FORBIDDEN", "SYNTHETIC sibling stopped")

        monkeypatch.setattr(scheduler, "execute", already_stopped)
        await scheduler.run_job(sibling)
        after = app.view(tid)
        assert after["lifecycle"] == "budget_exhausted"
        assert after["science_state"] == "sealed"
        assert after["delivery_ref"]
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, tid)
            assert delivery["status"] == "partial"
            assert delivery["run_outcome"] == "budget_exhausted"

    asyncio.run(run())
