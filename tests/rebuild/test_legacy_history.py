"""New synthetic old-schema DB validates compatibility, never scientific accuracy."""

import hashlib
import sqlite3
from uuid import uuid4

import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from fastapi.testclient import TestClient
from web.runtime_app import create_app


def make_database(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE tasks(task_id TEXT PRIMARY KEY,query TEXT,title TEXT,status TEXT,created_at TEXT,state_json TEXT,source TEXT)"
        )
        conn.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY,task_id TEXT,payload TEXT)")
        state = {
            "final_output": {
                "records": [{"record_id": "raw-only", "field_value": "9"}],
                "quality_report": {
                    "output_state": {"structured_data": {"json": {"records": [], "sources": []}}}
                },
            }
        }
        raw = canonical(state)
        conn.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
            (
                "old-synthetic",
                "SYNTHETIC query",
                "SYNTHETIC history",
                "failed",
                "2026-01-01T00:00:00Z",
                raw.decode(),
                "user",
            ),
        )
        conn.execute(
            "INSERT INTO events VALUES(?,?,?)",
            (
                4,
                "old-synthetic",
                canonical(
                    {"type": "question", "question": "SYNTHETIC old question without saved answer"}
                ).decode(),
            ),
        )
    return raw


def test_legacy_import_preserves_bytes_empty_final_list_and_cannot_execute(tmp_path):
    source = tmp_path / "synthetic-old.db"
    raw = make_database(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    app = Application(tmp_path / "data")
    first = app.legacy.import_database(source)
    second = app.legacy.import_database(source)
    assert first["imported_task_ids"] == second["imported_task_ids"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    tid = first["imported_task_ids"][0]
    state = app.view(tid)
    assert state["legacy"]["original_status"] == "failed" and state["read_only"] is True
    with app.repository.read() as conn:
        assert app.legacy.resource(conn, tid, state["delivery_ref"]["id"], "records") == []
        archive = app.legacy.get(conn, tid)
        _, path = app.artifacts.read_owned(tid, archive["state_artifact"]["artifact_id"])
        assert path.read_bytes() == raw
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    with pytest.raises(DomainError):
        app.repository.control(tid, "continue", str(uuid4()), state["revision"])
    replay = app.history.replay(tid, 10, str(uuid4()))
    replay_state = app.view(replay["task_id"])
    assert replay_state["pending"] is None and replay_state["legacy_version"] == 1
    assert any(item["title"] == "历史原始事件" for item in replay_state["replay"]["timeline"])
    assert app.budget.summary()["committed_micros"] == 0


def test_legacy_web_resources_do_not_masquerade_as_new_snapshot(tmp_path):
    source = tmp_path / "synthetic-old.db"
    make_database(source)
    app = create_app(tmp_path / "data", start_worker=False)
    tid = app.state.application.legacy.import_database(source)["imported_task_ids"][0]
    with TestClient(app) as client:
        delivery = client.get(f"/api/tasks/{tid}/delivery").json()
        assert delivery["legacy_version"] == 1 and delivery["scientific_validation"] is False
        records = client.get(
            f"/api/tasks/{tid}/deliveries/{delivery['delivery_id']}/records"
        ).json()
        assert records["items"] == [] and "snapshot_ref" not in records
        assert client.get(f"/api/tasks/{tid}/deliveries/wrong/records").status_code == 409
