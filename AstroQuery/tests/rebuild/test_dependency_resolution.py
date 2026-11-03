from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler
from uuid import uuid4


def test_budget_close_keeps_failed_metadata_edge_and_receipt_while_literature_continues(tmp_path):
    app = Application(tmp_path)
    tid = app.create("SYNTHETIC dependency audit", str(uuid4()))["task_id"]
    with app.repository.transaction() as conn:
        conn.execute("UPDATE jobs SET status='not_run' WHERE task_id=?", (tid,))
        parent = app.repository.enqueue(conn, tid, "M03", "catalog_discover", {})
        child = app.repository.enqueue(
            conn, tid, "M04", "literature_discover", {}, dependencies=[parent]
        )
        for name in ("catalog_hints", "catalog_discovery", "catalog_measurements"):
            app.repository.producer(conn, tid, name)
    scheduler = Scheduler(app)
    job = app.repository.claim_job(scheduler.owner_id)
    assert job["job_id"] == parent
    scheduler.fail(job, DomainError("MODULE_MODEL_LIMIT", "SYNTHETIC M03 branch cap"))
    with app.repository.read() as conn:
        edge = conn.execute(
            "SELECT * FROM job_dependencies WHERE job_id=? AND dependency_id=?", (child, parent)
        ).fetchone()
        assert edge["resolution"] == "closed_without_result" and edge["resolution_ref"]
        receipts = app.repository.objects(conn, tid, "dependency_resolution")
        assert len(receipts) == 1 and receipts[0]["scientific_read_granted"] is False
    assert app.repository.claim_job(scheduler.owner_id)["job_id"] == child
