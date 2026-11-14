"""Mount a selected terminal history on first read, independently of personal queries."""
import asyncio
import base64
import lzma
import hashlib
import io
if not hasattr(hashlib, 'file_digest'):
    def _file_digest(fileobj, digest_name='sha256'):
        h = getattr(hashlib, digest_name)() if isinstance(digest_name, str) else digest_name()
        for chunk in iter(lambda: fileobj.read(65536), b''):
            h.update(chunk)
        return h
    hashlib.file_digest = _file_digest
import json
import logging
import os
import queue
import sqlite3
import tempfile
import threading
from contextlib import closing, contextmanager
from functools import cached_property

from .errors import DomainError
from .paths import resource_root


TABLES = {'tasks', 'objects', 'events', 'jobs', 'job_dependencies', 'producers', 'reviews',
          'http_attempts', 'artifacts', 'artifact_refs', 'material_analysis_runs', 'agent_messages'}


class _ReadAhead(io.RawIOBase):
    """Overlap local decompression with SQLite writes using two 1 MiB slots.

    Keep JSON line assembly in BufferedReader, including arbitrarily long UTF-8
    lines. The producer holds at most one additional chunk, never parsed rows.
    The outer LZMA context continues to own the underlying stream.
    """
    def __init__(self, source):
        super().__init__()
        self.source = source
        self._queue = queue.Queue(maxsize=2)
        self._stopped = threading.Event()
        self._pending = memoryview(b'')
        self._ended, self._error = False, None
        self.worker = None
        worker = threading.Thread(target=self._produce, name='demo-decompress', daemon=True)
        worker.start()
        self.worker = worker

    def _put(self, item):
        while not self._stopped.is_set():
            try:
                self._queue.put(item, timeout=.05)
                return
            except queue.Full:
                pass

    def _produce(self):
        try:
            while not self._stopped.is_set():
                chunk = self.source.read(1024 * 1024)
                if not chunk:
                    break
                self._put((chunk, None))
            self._put((None, None))
        except BaseException as error:
            self._put((None, error))

    def readable(self):
        return True

    def readinto(self, target):
        if self.closed:
            raise ValueError('read of closed archive')
        if self._error is not None:
            raise self._error
        if not target or self._ended:
            return 0
        if not self._pending:
            data, error = self._queue.get()
            if error is not None:
                self._error = error
                raise error
            if data is None:
                self._ended = True
                return 0
            self._pending = memoryview(data)
        size = min(len(target), len(self._pending))
        target[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size

    def close(self):
        if not self.closed:
            self._stopped.set()
            if self.worker is not None and self.worker is not threading.current_thread():
                self.worker.join()
            self._pending, self._error = memoryview(b''), None
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        super().close()


class _ImportBatch:
    """Bound buffered rows while preserving archive order and the outer transaction."""
    def __init__(self, conn, columns):
        self.conn, self.columns = conn, columns
        self.key, self.sql, self.rows, self.size = None, None, [], 0

    def flush(self):
        if self.rows:
            self.conn.executemany(self.sql, self.rows)
            self.rows, self.size = [], 0

    def add(self, table, row, size):
        key = table, tuple(row)
        if key != self.key or len(self.rows) >= 500 or self.size + size > 8 * 1024**2:
            self.flush()
        if key != self.key:
            self.key = key
            conflict = ' OR IGNORE' if table in ('artifacts', 'artifact_refs') else ''
            self.sql = f"INSERT{conflict} INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})"
        self.rows.append(tuple(v.encode() if isinstance(v, str) and self.columns[table][k] == 'BLOB' else v for k, v in row.items()))
        self.size += size
        if self.size >= 8 * 1024**2:
            self.flush()  # A single original object can itself exceed the buffer budget.


def save_artifact(path, data, sha, *, allow_derived_hash=False):
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha and not allow_derived_hash:
        raise DomainError('DEMO_ORIGINAL_CHANGED', '来源返回了不同版本的原件', 409)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        name = stream.name
        try:
            stream.write(data)
        except BaseException:
            stream.close()
            os.unlink(name)
            raise
    try:
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class PublishedDemos:
    def __init__(self, application):
        self.app = application
        self.directory = resource_root() / 'demos'
        self.loaded = {}
        self.install_lock = threading.Lock()
        self._install_locks = {}
        self._import_slots = threading.BoundedSemaphore(2)
        self._write_lock = threading.Lock()
        self._checkpoint_slot = threading.BoundedSemaphore(1)
        self._checkpoint_thread = None

    @contextmanager
    def _defer_checkpoint(self):
        """Keep FULL WAL commit synchronous; checkpoint pages off the read path.

        An active second WAL connection prevents SQLite's last-close checkpoint.
        A busy maintenance slot uses the original automatic checkpoint instead
        of accumulating maintenance threads or unbounded pending work.
        """
        version = sqlite3.sqlite_version_info
        # Older engines have a WAL-reset race with concurrent checkpoints.
        # https://sqlite.org/wal.html#the_wal_reset_bug
        fixed = (version >= (3, 51, 3) or version[:2] == (3, 50) and version[2] >= 7
                 or version[:2] == (3, 44) and version[2] >= 6)
        if not fixed or not self._checkpoint_slot.acquire(blocking=False):
            yield False
            return
        ready, committed = threading.Event(), threading.Event()
        active = []
        def maintain():
            try:
                with closing(self.app.repository.connect()) as conn:
                    # Connecting alone does not open a WAL handle. Read the
                    # database before allowing the import transaction to begin.
                    conn.execute('SELECT 1 FROM tasks LIMIT 1').fetchone()
                    active.append(True)
                    ready.set()
                    committed.wait()
                    conn.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            except Exception:
                logging.getLogger(__name__).warning('Sample checkpoint maintenance unavailable', exc_info=True)
            finally:
                ready.set()
                self._checkpoint_slot.release()
        worker = threading.Thread(target=maintain, name='demo-checkpoint', daemon=True)
        try:
            worker.start()
        except RuntimeError:
            self._checkpoint_slot.release()
            yield False
            return
        self._checkpoint_thread = worker
        try:
            ready.wait()
            yield bool(active)
        finally:
            # The surrounding repository transaction has committed or rolled
            # back and closed its connection before maintenance may proceed.
            committed.set()

    def close(self):
        """Join the one bounded maintenance operation on application shutdown."""
        worker = self._checkpoint_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join()

    @cached_property
    def index(self):
        path = self.directory / 'index.json'
        return json.loads(path.read_bytes())['samples'] if path.is_file() else {}

    def open(self, task_id):
        """Return True for an imported demo. A user's original task always takes precedence."""
        if task_id not in self.index:
            return False
        if task_id in self.loaded:
            return self.loaded[task_id]
        with self.install_lock:
            lock = self._install_locks.setdefault(task_id, threading.Lock())
        with lock:
            if task_id in self.loaded:
                return self.loaded[task_id]
            repo = self.app.repository
            with repo.read() as conn:
                existing = conn.execute('SELECT 1 FROM tasks WHERE task_id=?', (task_id,)).fetchone()
                if existing:
                    origin = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='task_origin' AND object_id=? AND version=1", (task_id, task_id)).fetchone()
                    replica = bool(origin and json.loads(origin[0]).get('source') == 'sample')
                    if replica and self.index[task_id].get('public_messages'):
                        self._mount_messages(task_id,self.index[task_id])
                    self.loaded[task_id] = replica
                    return replica
            entry = self.index[task_id]
            if entry.get('public_messages'):
                from astroquery_ai.agent_harness.store import AgentStore
                AgentStore(repo)
            archive = self.directory / (task_id + '.jsonl.xz')
            with self._import_slots, archive.open('rb') as raw:
                if hashlib.file_digest(raw, 'sha256').hexdigest() != entry['sha256']:
                    raise DomainError('DEMO_HASH', '演示数据校验失败')
                raw.seek(0)
                with (lzma.open(raw, 'rb') as compressed,
                      io.BufferedReader(_ReadAhead(compressed), buffer_size=1024 * 1024) as stream,
                      self._write_lock,
                      self._defer_checkpoint() as deferred, repo.transaction() as conn):
                    if deferred:
                        conn.execute('PRAGMA wal_autocheckpoint=0')
                    kind, header = json.loads(next(stream))
                    if (kind != 'header' or header.get('format') != 'published-history/1'
                            or header.get('task_id') != task_id or header.get('snapshot_ref') != entry['snapshot_ref']):
                        raise DomainError('DEMO_ID', '演示修订与目录不一致')
                    columns = {table: {c[1]: c[2] for c in conn.execute(f'PRAGMA table_info({table})')} for table in TABLES}
                    batch = _ImportBatch(conn, columns)
                    for line in stream:
                        table, row = json.loads(line)
                        if table == 'table_bytes':
                            batch.flush()
                            sha = row['id']
                            if entry['media'].get(sha, {}).get('table') is not True:
                                raise DomainError('DEMO_TABLE', '该表不在所选样例内')
                            target = self.app.artifacts.path(f'objects/{sha[:2]}/{sha}')
                            save_artifact(target, base64.b64decode(row['data'], validate=True), sha)
                            continue
                        if table not in columns or row.keys() - columns[table].keys() or row.get('task_id', task_id) != task_id:
                            raise DomainError('DEMO_SCHEMA', '演示历史字段或所属任务不一致')
                        if table == 'material_analysis_runs':
                            state = json.loads(row['payload'])
                            if (row.get('status') not in {'complete','partial','failed','cancelled','interrupted'}
                                    or state.get('scope', {}).get('task_id') != task_id
                                    or not state.get('reports')
                                    or {'checkpoints','context','spec_ref'}.intersection(state)):
                                raise DomainError('DEMO_ANALYSIS', '演示补充索引必须为已保存的只读公开版本')
                        if table == 'agent_messages':
                            from .demo_messages import validate_public_message
                            try:
                                validate_public_message(row,task_id,entry['snapshot_ref'])
                            except (ValueError,TypeError) as error:
                                raise DomainError('DEMO_MESSAGE','演示追问必须是准确快照的公开终态') from error
                        batch.add(table, row, len(line))
                    batch.flush()
                    repo.put_object(conn, task_id, 'task_origin', task_id, 1, {'source': 'sample'})
            self.loaded[task_id] = True
            return True

    def _mount_messages(self,task_id,entry):
        """Backfill an installed demo without overwriting a local answer or user task."""
        from astroquery_ai.agent_harness.store import AgentStore
        from .demo_messages import validate_public_message
        repo=self.app.repository
        AgentStore(repo)
        rows=entry['public_messages']
        with repo.transaction() as conn:
            ref=json.loads(conn.execute('SELECT delivery_ref FROM tasks WHERE task_id=?',(task_id,)).fetchone()[0])
            for row in rows:
                try:validate_public_message(row,task_id,entry['snapshot_ref'])
                except (ValueError,TypeError) as error:raise DomainError('DEMO_MESSAGE','演示追问公开版本无效') from error
                scope=json.loads(row['scope'])
                if (scope['delivery_id'],scope['delivery_revision'])!=(ref['id'],ref['version']):
                    raise DomainError('DEMO_MESSAGE','演示追问属于另一交付版本')
                keys=list(row)
                conn.execute(f"INSERT OR IGNORE INTO agent_messages ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[row[k] for k in keys])

    async def prepare_request(self, request):
        path = request.url.path.strip('/').split('/')
        if len(path) < 3 or path[:2] != ['api', 'tasks'] or path[2] not in self.index:
            return
        task_id = path[2]
        # Already mounted samples need no disk read or wait on another import.
        replica = self.loaded.get(task_id)
        if replica is None:
            replica = await asyncio.to_thread(self.open, task_id)
        if (replica and request.method not in ('GET', 'HEAD', 'OPTIONS')
                and path[3:] not in (['exports'], ['exports', 'preview']) and path[3:4] != ['agent']):
            raise DomainError('READ_ONLY_DEMO', '演示样例仅供阅读和回放', 405)
        if replica and request.method == 'GET' and len(path) >= 5 and path[3] == 'artifacts':
            from .demo_originals import prepare_original
            await prepare_original(self.app, path[2], path[4], self.index[path[2]]['media'])
