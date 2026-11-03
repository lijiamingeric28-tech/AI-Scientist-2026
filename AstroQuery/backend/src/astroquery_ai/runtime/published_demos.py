"""Mount a selected terminal history on first read, independently of personal queries."""
import asyncio
import base64
import lzma
import hashlib
import json
import os
import tempfile
import threading
from functools import cached_property

from .errors import DomainError
from .paths import resource_root


TABLES = {'tasks', 'objects', 'events', 'jobs', 'job_dependencies', 'producers', 'reviews',
          'http_attempts', 'artifacts', 'artifact_refs'}


def save_artifact(path, data, sha):
    if hashlib.sha256(data).hexdigest() != sha:
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

    @cached_property
    def index(self):
        path = self.directory / 'index.json'
        return json.loads(path.read_bytes())['samples'] if path.is_file() else {}

    def open(self, task_id):
        """Return True for an imported demo. A user's original task always takes precedence."""
        if task_id not in self.index:
            return False
        with self.install_lock:
            if task_id in self.loaded:
                return self.loaded[task_id]
            repo = self.app.repository
            with repo.read() as conn:
                existing = conn.execute('SELECT 1 FROM tasks WHERE task_id=?', (task_id,)).fetchone()
                if existing:
                    origin = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='task_origin' AND object_id=? AND version=1", (task_id, task_id)).fetchone()
                    replica = bool(origin and json.loads(origin[0]).get('source') == 'sample')
                    self.loaded[task_id] = replica
                    return replica
            entry = self.index[task_id]
            archive = self.directory / (task_id + '.jsonl.xz')
            with archive.open('rb') as raw:
                if hashlib.file_digest(raw, 'sha256').hexdigest() != entry['sha256']:
                    raise DomainError('DEMO_HASH', '演示数据校验失败')
                raw.seek(0)
                with lzma.open(raw, 'rb') as stream, repo.transaction() as conn:
                    kind, header = json.loads(next(stream))
                    if (kind != 'header' or header.get('format') != 'published-history/1'
                            or header.get('task_id') != task_id or header.get('snapshot_ref') != entry['snapshot_ref']):
                        raise DomainError('DEMO_ID', '演示修订与目录不一致')
                    columns = {table: {c[1]: c[2] for c in conn.execute(f'PRAGMA table_info({table})')} for table in TABLES}
                    for line in stream:
                        table, row = json.loads(line)
                        if table == 'table_bytes':
                            sha = row['id']
                            if entry['media'].get(sha, {}).get('table') is not True:
                                raise DomainError('DEMO_TABLE', '该表不在所选样例内')
                            target = self.app.artifacts.path(f'objects/{sha[:2]}/{sha}')
                            save_artifact(target, base64.b64decode(row['data'], validate=True), sha)
                            continue
                        if table not in columns or row.keys() - columns[table].keys() or row.get('task_id', task_id) != task_id:
                            raise DomainError('DEMO_SCHEMA', '演示历史字段或所属任务不一致')
                        values = [v.encode() if isinstance(v, str) and columns[table][k] == 'BLOB' else v for k, v in row.items()]
                        conflict = ' OR IGNORE' if table in ('artifacts', 'artifact_refs') else ''
                        conn.execute(f"INSERT{conflict} INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", values)
                    repo.put_object(conn, task_id, 'task_origin', task_id, 1, {'source': 'sample'})
            self.loaded[task_id] = True
            return True

    async def prepare_request(self, request):
        path = request.url.path.strip('/').split('/')
        if len(path) < 3 or path[:2] != ['api', 'tasks'] or path[2] not in self.index:
            return
        replica = await asyncio.to_thread(self.open, path[2])
        if replica and request.method not in ('GET', 'HEAD', 'OPTIONS') and path[3:] != ['exports']:
            raise DomainError('READ_ONLY_DEMO', '演示样例仅供阅读和回放', 405)
        if replica and request.method == 'GET' and len(path) >= 5 and path[3] == 'artifacts':
            from .demo_originals import prepare_original
            await prepare_original(self.app, path[2], path[4], self.index[path[2]]['media'])
