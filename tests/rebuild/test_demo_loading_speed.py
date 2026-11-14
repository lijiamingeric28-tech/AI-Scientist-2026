"""Importer batching, exact data preservation, and concurrency without live services."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
import hashlib
import io
import json
import lzma
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.published_demos import PublishedDemos
from astroquery_ai.runtime.errors import DomainError

def archive(tmp_path,task_id='sample-a',count=1100,invalid=False):
    source=Repository(tmp_path/(task_id+'-source.sqlite3'))
    source.create_task('synthetic sample',task_id=task_id)
    with source.transaction() as c:
        c.execute("UPDATE tasks SET lifecycle='completed',science_state='sealed' WHERE task_id=?",(task_id,))
        for n in range(count):source.put_object(c,task_id,'measurement',str(n),1,{'literal':f'{n}.000','unit':'synthetic','uncertainty':{'raw':'0.10'}})
    snapshot={'id':'snapshot','version':1,'content_sha256':'a'*64}
    rows=[('header',{'format':'published-history/1','task_id':task_id,'snapshot_ref':snapshot})]
    with source.read() as c:
        for table in ('tasks','events','objects'):
            for r in c.execute(f'SELECT * FROM {table}'):
                rows.append((table,{k:v.decode() if isinstance(v,bytes) else v for k,v in dict(r).items()}))
    if invalid:rows.append(('objects',{'task_id':'wrong-task'}))
    pack=tmp_path/'packs';pack.mkdir(exist_ok=True);p=pack/(task_id+'.jsonl.xz')
    p.write_bytes(lzma.compress(b''.join(json.dumps(row,ensure_ascii=False).encode()+b'\n' for row in rows)))
    return pack,{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'snapshot_ref':snapshot,'media':{}},source

def service(tmp_path,pack,entries):
    repo=Repository(tmp_path/'dest.sqlite3');app=SimpleNamespace(repository=repo,artifacts=ArtifactStore(tmp_path/'artifacts',repo))
    demos=PublishedDemos(app);demos.directory=pack;demos.index=entries
    return demos,repo

def test_bulk_import_preserves_bytes_and_uses_bounded_batches(tmp_path):
    pack,entry,src=archive(tmp_path);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    sizes=[];transaction=repo.transaction
    class Connection:
        def __init__(self,c):self.c=c
        def __getattr__(self,k):return getattr(self.c,k)
        def executemany(self,sql,values):
            values=list(values);sizes.append(len(values));return self.c.executemany(sql,values)
    @contextmanager
    def observed():
        with transaction() as c:yield Connection(c)
    repo.transaction=observed
    assert demos.open('sample-a') is True
    with src.read() as a,repo.read() as b:
        assert [tuple(r) for r in a.execute("SELECT * FROM objects ORDER BY kind,object_id")] == [tuple(r) for r in b.execute("SELECT * FROM objects WHERE kind<>'task_origin' ORDER BY kind,object_id")]
    assert sizes and max(sizes)<=500 and max(sizes)>1

def test_different_sample_does_not_wait_for_other_archive_open(tmp_path,monkeypatch):
    pack,first,_=archive(tmp_path,'sample-a',2);_,second,_=archive(tmp_path,'sample-b',2)
    demos,repo=service(tmp_path,pack,{'sample-a':first,'sample-b':second})
    entered=threading.Event();release=threading.Event();opened=lzma.open
    def gated(file,*a,**kw):
        if str(getattr(file,'name','')).endswith('sample-a.jsonl.xz'):
            entered.set();assert release.wait(5)
        return opened(file,*a,**kw)
    monkeypatch.setattr(lzma,'open',gated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(demos.open,'sample-a');assert entered.wait(3)
        b=pool.submit(demos.open,'sample-b')
        try:assert b.result(timeout=1) is True
        finally:release.set()
        assert a.result() is True

def test_concurrent_same_sample_imports_once(tmp_path):
    pack,entry,_=archive(tmp_path,count=30);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    with ThreadPoolExecutor(max_workers=8) as pool:assert all(pool.map(demos.open,['sample-a']*8))
    with repo.read() as c:
        assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM objects WHERE kind='measurement'").fetchone()[0]==30

def test_late_invalid_record_rolls_back_and_can_retry(tmp_path):
    pack,entry,_=archive(tmp_path,invalid=True);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    with pytest.raises(DomainError,match='演示历史'):demos.open('sample-a')
    with repo.read() as c:assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    p=pack/'sample-a.jsonl.xz';lines=lzma.decompress(p.read_bytes()).splitlines();p.write_bytes(lzma.compress(b'\n'.join(lines[:-1])+b'\n'))
    entry['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();assert demos.open('sample-a') is True

def test_user_task_has_precedence_even_if_archive_is_invalid(tmp_path):
    pack,entry,_=archive(tmp_path,count=2);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    repo.create_task('user original',task_id='sample-a');(pack/'sample-a.jsonl.xz').write_bytes(b'bad')
    assert demos.open('sample-a') is False
    with repo.read() as c:assert repo.task(c,'sample-a')['title']=='user original'

def test_distinct_import_writers_wait_outside_sqlite_busy_timeout(tmp_path,monkeypatch):
    pack,a,_=archive(tmp_path,'sample-a',2);_,b,_=archive(tmp_path,'sample-b',2)
    demos,repo=service(tmp_path,pack,{'sample-a':a,'sample-b':b})
    entered=threading.Event();release=threading.Event();second_open=threading.Event();local=threading.local()
    connect,transaction,opened=repo.connect,repo.transaction,lzma.open
    def short_connect():
        c=connect();c.execute('PRAGMA busy_timeout=25');return c
    repo.connect=short_connect
    @contextmanager
    def held_transaction():
        with transaction() as c:
            if local.task=='sample-a':entered.set();assert release.wait(5)
            yield c
    repo.transaction=held_transaction
    def observe_open(file,*a,**kw):
        stream=opened(file,*a,**kw)
        if local.task=='sample-b':second_open.set()
        return stream
    monkeypatch.setattr(lzma,'open',observe_open)
    def run(tid):local.task=tid;return demos.open(tid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run,'sample-a');assert entered.wait(3)
        second=pool.submit(run,'sample-b');assert second_open.wait(3)
        try:
            with pytest.raises(FutureTimeout):second.result(timeout=.2)
        finally:release.set()
        assert first.result() and second.result()


def test_durable_import_does_not_wait_for_checkpoint(tmp_path):
    pack,entry,source=archive(tmp_path,count=30);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    entered=threading.Event();release=threading.Event();connect=repo.connect;commits=[]
    class Connection:
        def __init__(self,c):self.c=c
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,*a):
            if sql=='PRAGMA wal_checkpoint(PASSIVE)':
                entered.set();assert release.wait(5)
            return self.c.execute(sql,*a)
        def commit(self):
            commits.append((self.c.execute('PRAGMA synchronous').fetchone()[0],
                            self.c.execute('PRAGMA foreign_keys').fetchone()[0]))
            return self.c.commit()
    repo.connect=lambda:Connection(connect())
    try:
        assert demos.open('sample-a') is True
        assert entered.wait(1),'checkpoint must run outside the completed import'
        with source.read() as a,repo.read() as b:
            assert [tuple(r) for r in a.execute('SELECT * FROM objects ORDER BY kind,object_id')] == [
                tuple(r) for r in b.execute("SELECT * FROM objects WHERE kind<>'task_origin' ORDER BY kind,object_id")]
            assert b.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert commits==[(2,1)]
    finally:
        release.set()
        if hasattr(demos,'close'):demos.close()


def test_checkpoint_slot_is_bounded_and_shutdown_waits(tmp_path):
    pack,a,_=archive(tmp_path,'sample-a',3);_,b,_=archive(tmp_path,'sample-b',3)
    demos,repo=service(tmp_path,pack,{'sample-a':a,'sample-b':b})
    entered=threading.Event();release=threading.Event();connect=repo.connect;checkpoints=[]
    class Connection:
        def __init__(self,c):self.c=c
        def __getattr__(self,k):return getattr(self.c,k)
        def execute(self,sql,*a):
            if sql=='PRAGMA wal_checkpoint(PASSIVE)':
                checkpoints.append(threading.get_ident());entered.set();assert release.wait(5)
            return self.c.execute(sql,*a)
    repo.connect=lambda:Connection(connect())
    try:
        assert demos.open('sample-a')
        assert entered.wait(1),'a single background checkpoint must be started'
        assert demos.open('sample-b')
        assert len(checkpoints)==1
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing=pool.submit(demos.close)
            try:
                with pytest.raises(FutureTimeout):closing.result(timeout=.1)
            finally:release.set()
            closing.result(timeout=3)
    finally:
        release.set()
        if hasattr(demos,'close'):demos.close()


def test_anchor_failure_falls_back_without_changing_commit_strength(tmp_path,caplog):
    pack,entry,_=archive(tmp_path,count=3);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    connect=repo.connect
    def failed_anchor():
        if threading.current_thread().name=='demo-checkpoint':raise sqlite3.OperationalError('anchor unavailable')
        return connect()
    repo.connect=failed_anchor
    try:
        assert demos.open('sample-a')
        with repo.read() as c:
            assert c.execute('PRAGMA synchronous').fetchone()[0]==2
            assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1
            assert c.execute('PRAGMA wal_autocheckpoint').fetchone()[0]==1000
            assert c.execute("SELECT count(*) FROM objects WHERE kind='measurement'").fetchone()[0]==3
        assert 'checkpoint maintenance unavailable' in caplog.text
    finally:demos.close()


def test_failed_commit_rolls_back_and_releases_maintenance_for_retry(tmp_path):
    pack,entry,_=archive(tmp_path,count=3);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    connect=repo.connect;fail=[True]
    class Connection:
        def __init__(self,c):self.c=c
        def __getattr__(self,k):return getattr(self.c,k)
        def commit(self):
            if fail[0]:raise sqlite3.OperationalError('simulated disk full')
            return self.c.commit()
    repo.connect=lambda:Connection(connect())
    try:
        with pytest.raises(sqlite3.OperationalError,match='disk full'):demos.open('sample-a')
        demos.close()
        with repo.read() as c:assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
        assert 'sample-a' not in demos.loaded
        fail[0]=False
        assert demos.open('sample-a')
    finally:demos.close()


def test_truncated_compressed_tail_rolls_back_all_imported_rows(tmp_path):
    pack,entry,_=archive(tmp_path,count=3);demos,repo=service(tmp_path,pack,{'sample-a':entry})
    p=pack/'sample-a.jsonl.xz';original=p.read_bytes();p.write_bytes(original[:-15]);entry['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    try:
        with pytest.raises(EOFError):demos.open('sample-a')
        demos.close()
        with repo.read() as c:assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
        p.write_bytes(original);entry['sha256']=hashlib.sha256(original).hexdigest()
        assert demos.open('sample-a')
    finally:demos.close()


def test_abrupt_process_exit_before_checkpoint_preserves_complete_import(tmp_path):
    pack,entry,source=archive(tmp_path,count=30)
    code=textwrap.dedent('''
        import json,os,sys,threading
        from pathlib import Path
        from types import SimpleNamespace
        from astroquery_ai.runtime.repository import Repository
        from astroquery_ai.runtime.storage import ArtifactStore
        from astroquery_ai.runtime.published_demos import PublishedDemos
        root=Path(sys.argv[1]);repo=Repository(root/'crash.sqlite3');connect=repo.connect;entered=threading.Event()
        class Connection:
            def __init__(self,c):self.c=c
            def __getattr__(self,k):return getattr(self.c,k)
            def execute(self,sql,*args):
                if sql=='PRAGMA wal_checkpoint(PASSIVE)':
                    entered.set();threading.Event().wait(30)
                return self.c.execute(sql,*args)
        repo.connect=lambda:Connection(connect())
        app=SimpleNamespace(repository=repo,artifacts=ArtifactStore(root/'crash-artifacts',repo))
        demos=PublishedDemos(app);demos.directory=root/'packs';demos.index={'sample-a':json.loads(sys.argv[2])}
        assert demos.open('sample-a')
        assert entered.wait(3)
        os._exit(0)
    ''')
    import astroquery_ai.runtime.published_demos as module
    env={**os.environ,'PYTHONPATH':str(Path(module.__file__).resolve().parents[2])}
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path),json.dumps(entry)],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    recovered=Repository(tmp_path/'crash.sqlite3')
    with source.read() as a,recovered.read() as b:
        assert [tuple(r) for r in a.execute('SELECT * FROM objects ORDER BY kind,object_id')] == [
            tuple(r) for r in b.execute("SELECT * FROM objects WHERE kind<>'task_origin' ORDER BY kind,object_id")]
        assert b.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_interrupted_anchor_preparation_does_not_leave_maintenance_waiting(tmp_path,monkeypatch):
    pack,entry,_=archive(tmp_path,count=3);demos,_=service(tmp_path,pack,{'sample-a':entry})
    event=threading.Event;created=[]
    class InterruptedReady:
        def __init__(self):self.event=event()
        def set(self):self.event.set()
        def wait(self):
            assert self.event.wait(3)
            raise KeyboardInterrupt()
    def make_event():
        item=InterruptedReady() if not created else event();created.append(item);return item
    monkeypatch.setattr(threading,'Event',make_event)
    try:
        with pytest.raises(KeyboardInterrupt):
            with demos._defer_checkpoint():
                pytest.fail('interrupted preparation must not enter the writer')
        demos._checkpoint_thread.join(timeout=.5)
        assert not demos._checkpoint_thread.is_alive(),'interruption must release the prepared WAL anchor'
    finally:
        if len(created)>1:created[1].set()
        demos.close()


def test_read_ahead_is_bounded_and_preserves_large_unicode_lines():
    from astroquery_ai.runtime import published_demos as module
    reader_type=getattr(module,'_ReadAhead',None)
    assert reader_type is not None,'decompression must overlap writing with bounded read-ahead'
    payload=json.dumps({'raw':'光谱与误差\n'*400000},ensure_ascii=False).encode()+b'\n'
    filled=threading.Event();calls=[]
    class Source(io.BytesIO):
        def read(self,n=-1):
            calls.append(n)
            if len(calls)==3:filled.set()
            return super().read(n)
    source=Source(payload)
    raw=reader_type(source)
    try:
        assert filled.wait(2)
        assert len(calls)==3 and max(calls)<=1024*1024
        with io.BufferedReader(raw,buffer_size=1024*1024) as reader:
            assert list(reader)==[payload]
            assert reader.read()==b''
    finally:raw.close()
    assert not raw.worker.is_alive()
    assert not source.closed,'the outer archive context owns the original stream'


def test_read_ahead_failure_propagates_and_close_joins_a_full_queue():
    from astroquery_ai.runtime import published_demos as module
    reader_type=getattr(module,'_ReadAhead',None)
    assert reader_type is not None,'read-ahead must preserve terminal decompression errors'
    class Broken(io.BytesIO):
        def read(self,n=-1):raise EOFError('compressed footer missing')
    raw=reader_type(Broken())
    with pytest.raises(EOFError,match='footer missing'):
        with io.BufferedReader(raw) as stream:stream.read()
    assert not raw.worker.is_alive()


    filled=threading.Event()
    class Source(io.BytesIO):
        calls=0
        def read(self,n=-1):
            self.calls+=1
            if self.calls==3:filled.set()
            return super().read(n)
    raw=reader_type(Source(b'x'*(8*1024*1024)))
    try:assert filled.wait(2)
    finally:raw.close()
    assert not raw.worker.is_alive()


@pytest.mark.parametrize('version,enabled',[
    ((3,44,5),False),((3,44,6),True),((3,50,6),False),((3,50,7),True),
    ((3,51,2),False),((3,51,3),True),((3,53,2),True),
])
def test_background_checkpoint_requires_wal_reset_fix(tmp_path,monkeypatch,version,enabled):
    pack,entry,_=archive(tmp_path,count=2);demos,_=service(tmp_path,pack,{'sample-a':entry})
    monkeypatch.setattr(sqlite3,'sqlite_version_info',version)
    try:
        with demos._defer_checkpoint() as deferred:assert deferred is enabled
    finally:demos.close()
