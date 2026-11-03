from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from astroquery_ai.runtime.application import Application
from web.runtime_app import create_app


def test_config_compare_and_swap_is_shared_by_independent_instances(tmp_path):
    from astroquery_ai.runtime.configuration import Configuration
    from astroquery_ai.runtime.errors import DomainError

    first, second = Configuration(tmp_path), Configuration(tmp_path)

    def save(configuration):
        try:
            return configuration.save({"unpaywall_email": "synthetic@example.org"}, 1)[
                "saved_revision"
            ]
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, [first, second]))
    assert sorted(map(str, outcomes)) == ["2", "CONFIG_CHANGED"]
    assert Configuration(tmp_path).saved["revision"] == 2


def test_http_rejects_wrong_top_level_and_boolean_revision(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        for invalid in (
            [],
            None,
            "text",
            3,
            {"query": "x", "operation_id": str(uuid4()), "expected_revision": True},
        ):
            response = client.post(
                "/api/tasks",
                content=__import__("json").dumps(invalid),
                headers={"content-type": "application/json"},
            )
            assert response.status_code == 422
        response = client.post(
            "/api/tasks/batch-delete", json={"task_ids": [{}], "operation_id": str(uuid4())}
        )
        assert response.status_code == 422


def test_import_and_startup_do_not_create_scientific_calls(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/budget").json()["actual_micros"] == 0
        assert client.get("/api/config").json()["setup_complete"] is False


def test_ordinary_creation_cannot_enable_pilot_or_supply_scientific_answers(tmp_path):
    api = create_app(tmp_path, start_worker=False)
    with TestClient(api) as client:
        for key, value in [('pilot_scope', {'enabled': True}), ('source_seeds', ['synthetic/table']),
                           ('confirmed_query', {}), ('row', 1), ('column', 'Value'),
                           ('historical_answers', ['synthetic answer'])]:
            response = client.post('/api/tasks', json={'query':'SYNTHETIC input',
                'operation_id':str(uuid4()), key:value})
            assert response.status_code == 422
        application = api.state.application
        with application.repository.read() as c:
            assert c.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
            assert c.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_creation_retransmission_is_one_task_and_one_parse_job(tmp_path):
    application = Application(tmp_path)
    operation_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: application.create("SYNTHETIC fresh request", operation_id), range(4)
            )
        )
    assert {r["task_id"] for r in results} == {operation_id}
    with application.repository.read() as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_missing_registry_is_pause_and_zero_paid_calls(tmp_path):
    import asyncio
    from astroquery_ai.runtime.scheduler import Scheduler

    application = Application(tmp_path)
    task = application.create("SYNTHETIC missing registry", str(uuid4()))
    scheduler = Scheduler(application)
    job = application.repository.claim_job("synthetic-worker")
    try:
        asyncio.run(application.prepare(job))
    except Exception as error:
        scheduler.fail(job, error)
    state = application.view(task["task_id"])
    assert state["lifecycle"] == "paused"
    assert state["draft"]["pause_reason"] == "registry_unavailable"
    assert application.budget.summary()["committed_micros"] == 0


def test_http_rejects_old_resume_upload_and_record_mutation(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        task = client.post(
            "/api/tasks", json={"query": "SYNTHETIC", "operation_id": str(uuid4())}
        ).json()
        tid = task["task_id"]
        assert client.post(f"/api/tasks/{tid}/resume", json={"answer": "y"}).status_code == 410
        assert client.post("/api/upload").status_code == 410
        assert client.delete(f"/api/tasks/{tid}/records/any").status_code == 410
        assert client.post(f"/api/tasks/{tid}/exports", json={}).status_code == 422
        assert client.get(f"/api/tasks/{tid}/delivery").status_code == 409


def test_control_rejects_extra_execution_overrides_and_cross_origin(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        task = client.post(
            "/api/tasks", json={"query": "SYNTHETIC", "operation_id": str(uuid4())}
        ).json()
        response = client.post(
            f"/api/tasks/{task['task_id']}/continue",
            json={
                "operation_id": str(uuid4()),
                "expected_revision": task["revision"],
                "query": "change identity",
            },
        )
        assert response.status_code == 422
        assert (
            client.post(
                "/api/tasks",
                json={"query": "x", "operation_id": str(uuid4())},
                headers={"Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )


def test_restart_requires_explicit_resume_and_keeps_draft(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        task = client.post(
            "/api/tasks",
            json={"query": "SYNTHETIC interrupted preparation", "operation_id": str(uuid4())},
        ).json()
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        state = client.get(f"/api/tasks/{task['task_id']}/state").json()
        assert state["lifecycle"] == "interrupted"
        assert state["resume_required"] == 1
        assert state["draft"]["status"] == "paused"
        assert state["draft"]["pause_reason"] == "process_interrupted"
        assert client.get("/api/budget").json()["committed_micros"] == 0
