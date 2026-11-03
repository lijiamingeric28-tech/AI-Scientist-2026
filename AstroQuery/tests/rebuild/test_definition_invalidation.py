import asyncio
from uuid import uuid4

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.scenario import application, run_until_wait


def test_transitive_conversion_policy_revocation_closes_work_and_quarantines_without_losing_original(
    tmp_path, monkeypatch,
):
    from copy import deepcopy
    from astroquery_ai.runtime import run_policy
    monkeypatch.setattr(run_policy, 'request_policy', lambda _, preferences=None: deepcopy(run_policy.LEGACY_RUN_POLICY))
    async def run():
        app = application(tmp_path / "data")
        scheduler = Scheduler(app)
        tid = app.create("SYNTHETIC_AQ 测试长度", str(uuid4()))["task_id"]
        await run_until_wait(app, scheduler)
        state = app.view(tid)
        app.draft_action(
            tid,
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
        while job := app.repository.claim_job(scheduler.owner_id, lease_seconds=600):
            if job["kind"] == "finalize":
                with app.repository.transaction() as conn:
                    before = app.repository.objects(conn, tid, "measurement")
                    assert len(before) == 1
                    conn.execute(
                        "INSERT INTO revocations(event_id,release_id,dependency_id,reason,evidence) VALUES(?,?,?,?,?)",
                        (
                            "synthetic-policy-withdrawal",
                            "synthetic-registry-v1",
                            "synthetic-same-length",
                            "SYNTHETIC policy withdrawal",
                            canonical({"synthetic": True}),
                        ),
                    )
                try:
                    await scheduler.dispatch(job)
                except DomainError as exc:
                    assert exc.code == "DEFINITION_INVALIDATED"
                    scheduler.fail(job, exc)
                else:
                    raise AssertionError("Revoked transitive policy was ignored")
                break
            await scheduler.dispatch(job)
        state = app.view(tid)
        assert state["lifecycle"] == "definition_invalidated" and state["science_state"] == "sealed"
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, tid)
            assert delivery["measurements"] == []
            assert app.repository.objects(conn, tid, "measurement") == before
            assert not conn.execute(
                "SELECT 1 FROM producers WHERE task_id=? AND state='open'", (tid,)
            ).fetchone()
            assert not conn.execute(
                "SELECT 1 FROM jobs WHERE task_id=? AND status IN ('ready','running')", (tid,)
            ).fetchone()

    asyncio.run(run())
