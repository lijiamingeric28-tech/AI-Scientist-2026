import asyncio

import httpx
import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import digest, utcnow
from astroquery_ai.runtime.errors import DomainError


def test_unknown_network_reservations_survive_restart_and_bound_bytes_and_each_branch(tmp_path):
    async def run():
        app = Application(tmp_path)
        task = app.repository.create_task("SYNTHETIC HTTP crash budget", kind="validation")
        tid = task["task_id"]
        with app.repository.transaction() as conn:
            app.repository.put_object(
                conn,
                tid,
                "calibration_scope",
                tid,
                1,
                {"allowed_owners": ["M05"], "allowed_services": ["publisher"], "max_requests": 10},
            )
            conn.execute(
                "INSERT INTO http_attempts(attempt_id,task_id,owner,service,request_hash,status,started_at,byte_bound,wall_bound_seconds,resource_scope) VALUES(?,?,?,?,?,'dispatched',?,?,?,?)",
                (
                    "synthetic-crashed-request",
                    tid,
                    "M05",
                    "publisher",
                    digest({"synthetic": True}),
                    utcnow(),
                    32,
                    1800,
                    "attachment",
                ),
            )
        app.repository.recover()
        with app.repository.transaction() as conn:
            app.repository.mutate_task(conn, tid, lifecycle="running")
        captures = []

        def handle(request):
            captures.append(request)
            return httpx.Response(200, content=b"SYNTHETIC")

        app.http.transport = httpx.MockTransport(handle)
        await app.http.request(tid, "M05", "publisher", "GET", "https://example.test/data", resource_scope="attachment")
        assert len(captures) == 1  # old cumulative clock no longer cuts off normal work
        await app.http.request(
            tid, "M05", "publisher", "GET", "https://example.test/body", resource_scope="body"
        )
        assert len(captures) == 2
        with app.repository.transaction() as conn:
            row = conn.execute(
                "SELECT status,byte_bound FROM http_attempts WHERE attempt_id='synthetic-crashed-request'"
            ).fetchone()
            assert row["status"] == "unknown" and row["byte_bound"] == 32
            conn.execute(
                "UPDATE http_attempts SET byte_bound=? WHERE attempt_id='synthetic-crashed-request'",
                (2 * 1024**3,),
            )
        with pytest.raises(DomainError) as caught:
            await app.http.request(
                tid, "M05", "publisher", "GET", "https://example.test/body-two", max_bytes=1
            )
        assert caught.value.code == "MODULE_HTTP_BYTE_LIMIT" and len(captures) == 2

    asyncio.run(run())


def test_container_expansion_reservations_share_network_byte_cap_after_restart(tmp_path):
    async def run():
        app = Application(tmp_path)
        tid = app.repository.create_task('SYNTHETIC local expansion and network shared budget', kind='validation')['task_id']
        with app.repository.transaction() as conn:
            app.repository.put_object(conn, tid, 'calibration_scope', tid, 1,
                {'allowed_owners': ['M05'], 'allowed_services': ['publisher'], 'max_requests': 2})
            for index in range(64):
                app.repository.put_object(conn, tid, 'source_resource', 'synthetic-expansion-' + str(index), 1,
                    {'kind': 'container_expansion', 'owner': 'M05', 'state': 'reserved', 'byte_bound': 32 * 1024**2, 'actual_bytes': None})
        restarted = Application(tmp_path)
        captured = []
        restarted.http.transport = httpx.MockTransport(lambda request: captured.append(request))
        with pytest.raises(DomainError) as error:
            await restarted.http.request(tid, 'M05', 'publisher', 'GET', 'https://example.test/next', max_bytes=1)
        assert error.value.code == 'MODULE_HTTP_BYTE_LIMIT' and captured == []
    asyncio.run(run())
