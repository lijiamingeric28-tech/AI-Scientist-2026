"""Bounded execution read models, keyed by authoritative SQLite inputs."""
from collections import OrderedDict
from hashlib import sha256
from threading import RLock

from .presentation import history_scope


class ExecutionCache:
    def __init__(self):
        self.lock = RLock()
        self.values = OrderedDict()
        self.bytes = 0


def reconstruction(application, task_id, cursor, build):
    cache = application.__dict__.setdefault('_execution_read_cache', ExecutionCache())
    with application.repository.read() as conn:
        task, source, position, capture = history_scope(application, conn, task_id, cursor)
        signature = sha256(repr((task_id, task, source, position, capture, 'execution-cache/1')).encode())
        event_payloads = []
        # No model parsing, scientific objects or current job status is trusted
        # in place of history. Include mutable receipts, dependency edges and
        # raw event identity/content so same-cursor repairs invalidate the model.
        for sql in (
            'SELECT seq,event_id,payload FROM events WHERE task_id=? AND seq<=? ORDER BY seq',
            'SELECT job_id,kind,created_at,payload FROM jobs WHERE task_id=? ORDER BY job_id',
            'SELECT d.* FROM job_dependencies d JOIN jobs j ON j.job_id=d.job_id WHERE j.task_id=? ORDER BY d.job_id,d.dependency_id',
            'SELECT attempt_id,job_id,model,status,created_at,dispatched_at,settled_at,receipt FROM attempts WHERE task_id=? ORDER BY attempt_id',
            'SELECT attempt_id,service,status,started_at,completed_at,status_code,error_code,request_hash FROM http_attempts WHERE task_id=? ORDER BY attempt_id',
            "SELECT object_id,version,content_sha256,created_at FROM objects WHERE task_id=? AND kind='dependency_resolution' ORDER BY object_id,version",
        ):
            args = (source, position) if 'seq<=?' in sql else (source,)
            for row in conn.execute(sql, args):
                signature.update(repr(tuple(row)).encode())
                if 'seq<=?' in sql:
                    event_payloads.append(row['payload'])
        key = signature.digest()
        with cache.lock:
            if key in cache.values:
                cache.values.move_to_end(key)
                return cache.values[key][0]
            # Keep validation and construction in the same database snapshot;
            # concurrent sections wait for this exact reconstruction.
            value = build(conn, event_payloads)
            size = len(repr(value))
            if size <= 24 * 1024 * 1024:
                cache.values[key] = (value, size)
                cache.bytes += size
                while len(cache.values) > 8 or cache.bytes > 24 * 1024 * 1024:
                    _, (_, removed) = cache.values.popitem(last=False)
                    cache.bytes -= removed
            return value
