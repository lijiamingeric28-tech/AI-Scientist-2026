"""Warm projections reuse parsing; backward seeks never borrow future facts."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from astroquery_ai.api.http import create_app
from astroquery_ai.application.presentation import presentation


@pytest.fixture
def committed_clock(monkeypatch):
    """Keep object/event ordering observable even below the host clock resolution."""
    ticks = count()
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr('astroquery_ai.runtime.repository.utcnow',
                        lambda: (epoch + timedelta(microseconds=100 * next(ticks))).isoformat())


def test_warm_projection_avoids_payload_queries_and_incremental_history_starts_after_checkpoint(tmp_path, committed_clock):
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC checkpoint', str(uuid4()))['task_id']
    # Creation saves the draft after its initial event. Warm the cache only
    # once every fixture object is visible at an explicit committed cutoff.
    with app.repository.transaction() as conn:
        app.repository.event(conn, tid, 'fixture_ready', {})
    before = presentation(app, tid, include_chat_activity=True)
    original_read = app.repository.read
    queries = []

    @contextmanager
    def traced():
        with original_read() as conn:
            conn.set_trace_callback(queries.append)
            yield conn

    app.repository.read = traced
    assert presentation(app, tid, include_chat_activity=True) == before
    assert not any('SELECT payload FROM events' in query for query in queries)
    assert not any('SELECT payload FROM objects' in query for query in queries)
    with app.repository.transaction() as conn:
        event = app.repository.event(conn, tid, 'execution_stage_changed', {'stage_id': 'quality'})
    queries.clear()
    after = presentation(app, tid, include_chat_activity=True)
    assert after['active_stage'] == 'quality_check'
    assert after['cursor'] == event['seq']
    reads = [query for query in queries if 'SELECT payload FROM events' in query]
    assert len(reads) == 1 and f"seq>{before['cursor']}" in reads[0]
    assert not any('SELECT payload FROM objects o' in query for query in queries)
    past = presentation(app, tid, before['cursor'], include_chat_activity=True)
    assert past['active_stage'] == before['active_stage']
    assert past['messages'] == before['messages']
    assert past['milestones'] == before['milestones']
    assert past['historical'] is True


def test_advancing_cutoff_decodes_newly_visible_objects(tmp_path, committed_clock):
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC cutoff visibility', str(uuid4()))['task_id']
    with app.repository.transaction() as conn:
        app.repository.event(conn, tid, 'fixture_ready', {})
    before = presentation(app, tid)
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, tid, 'source', 'later', 1, {'source_id': 'later'})
        created_at = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='source'",
                                  (tid,)).fetchone()[0]
    # An object 100 microseconds after the cutoff remains invisible even
    # though its metadata now exists and has invalidated the outer cache.
    assert datetime.fromisoformat(created_at) - datetime.fromisoformat(before['at']) == timedelta(microseconds=100)
    assert presentation(app, tid)['counts']['sources'] == 0
    with app.repository.transaction() as conn:
        app.repository.event(conn, tid, 'fixture_source_visible', {})
    original_read = app.repository.read
    queries = []

    @contextmanager
    def traced():
        with original_read() as conn:
            conn.set_trace_callback(queries.append)
            yield conn

    app.repository.read = traced
    after = presentation(app, tid)
    assert after['counts']['sources'] == 1
    assert any('SELECT payload FROM objects o' in query and "kind='source'" in query for query in queries)
    assert presentation(app, tid, before['cursor'])['counts']['sources'] == 0


def test_cached_projection_does_not_hide_same_cursor_object_changes_or_mutate_shared_data(tmp_path):
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC cache invalidation', str(uuid4()))['task_id']
    before = presentation(app, tid)
    before['messages'].clear()
    assert presentation(app, tid)['messages']
    with app.repository.transaction() as conn:
        # A saved object's timestamp may precede an already committed event,
        # e.g. import. Cache validity cannot rely on task revision alone.
        app.repository.put_object(conn, tid, 'source', 's', 1, {'source_id': 's'})
        conn.execute("UPDATE objects SET created_at=? WHERE task_id=? AND object_id='s'",
                     (before['at'], tid))
    after = presentation(app, tid)
    assert after['cursor'] == before['cursor']
    assert after['counts']['sources'] == 1


def test_forward_and_backward_checkpoints_equal_complete_reconstruction(tmp_path):
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC timeline', str(uuid4()))['task_id']
    cursors = []
    events = [('execution_stage_changed', {'stage_id': 'quality'}),
              ('review_ready', {'review_id': 'review'}),
              ('task_state_changed', {'lifecycle': 'waiting_review'}),
              ('unrelated_log', {}), ('review_applied', {'review_id': 'review'}),
              ('execution_stage_changed', {'stage_id': 'normalization'}),
              ('task_state_changed', {'lifecycle': 'paused'}),
              ('task_state_changed', {'lifecycle': 'running'}),
              ('task_state_changed', {'lifecycle': 'completed'})]
    for kind, payload in events:
        with app.repository.transaction() as conn:
            cursors.append(app.repository.event(conn, tid, kind, payload)['seq'])
        presentation(app, tid)
    for cursor in [*cursors, *reversed(cursors), cursors[3], cursors[-1]]:
        cached = presentation(app, tid, cursor, True)
        saved = app.__dict__.pop('_presentation_read_cache')
        rebuilt = presentation(app, tid, cursor, True)
        app._presentation_read_cache = saved
        assert cached == rebuilt
    assert presentation(app, tid, cursors[2])['lifecycle'] == 'waiting_review'
    assert presentation(app, tid, cursors[4])['lifecycle'] == 'running'
    assert presentation(app, tid, cursors[6])['lifecycle'] == 'paused'
