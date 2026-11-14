"""Bounded, disposable read caches; authoritative state is always read in SQLite."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from threading import RLock

from astroquery_ai.runtime.codec import loads


class ReadCache:
    def __init__(self):
        self.lock = RLock()
        self.projections = OrderedDict()
        self.histories = OrderedDict()
        self.folds = OrderedDict()
        self.objects = OrderedDict()


def cache_for(application):
    return application.__dict__.setdefault('_presentation_read_cache', ReadCache())


def dependencies(conn, task, source, cursor, activity, limit):
    """Hash identities, not parsed scientific bodies; mutable reviews stay exact."""
    signature = sha256(repr((task, source, cursor, activity, limit, 'TaskPresentation/1')).encode())
    for sql in (
        'SELECT kind,object_id,version,content_sha256,created_at FROM objects WHERE task_id=? ORDER BY kind,object_id,version',
        'SELECT * FROM reviews WHERE task_id=? ORDER BY review_id',
        'SELECT * FROM jobs WHERE task_id=? ORDER BY job_id',
        'SELECT seq,event_id FROM events WHERE task_id=? ORDER BY seq',
        'SELECT a.*,r.owner_id FROM artifact_refs r JOIN artifacts a ON a.artifact_id=r.artifact_id WHERE r.task_id=? ORDER BY a.artifact_id,r.owner_id',
    ):
        for row in conn.execute(sql, (source,)):
            signature.update(repr(tuple(row)).encode())
    return signature.hexdigest()


def cached_projection(cache, key):
    with cache.lock:
        if key not in cache.projections:
            return None
        cache.projections.move_to_end(key)
        return deepcopy(cache.projections[key][0])


def save_projection(cache, key, value):
    size = len(repr(value))
    if size > 4_000_000:
        return
    with cache.lock:
        cache.projections[key] = (deepcopy(value), size)
        cache.projections.move_to_end(key)
        while len(cache.projections) > 16 or sum(v[1] for v in cache.projections.values()) > 12_000_000:
            cache.projections.popitem(last=False)


def cached_objects(application, conn, source, kind, cutoff, read):
    cache = cache_for(application)
    identities = tuple(tuple(row) for row in conn.execute(
        '''SELECT object_id,version,content_sha256,created_at FROM objects o
        WHERE task_id=? AND kind=? AND created_at<=? AND version=(
        SELECT max(version) FROM objects i WHERE i.task_id=o.task_id AND i.kind=o.kind
        AND i.object_id=o.object_id AND i.created_at<=?) ORDER BY created_at,object_id''',
        (source, kind, cutoff, cutoff)))
    key = (source, kind, identities)
    with cache.lock:
        if key in cache.objects:
            cache.objects.move_to_end(key)
            return deepcopy(cache.objects[key][0])
    result = read()
    size = len(repr(result))
    if size <= 4_000_000:
        with cache.lock:
            cache.objects[key] = (deepcopy(result), size)
            cache.objects.move_to_end(key)
            while len(cache.objects) > 128 or sum(v[1] for v in cache.objects.values()) > 12_000_000:
                cache.objects.popitem(last=False)
    return result


def history_rows(application, conn, source, cursor):
    cache = cache_for(application)
    positions = tuple(tuple(row) for row in conn.execute(
        'SELECT seq,event_id FROM events WHERE task_id=? AND seq<=? ORDER BY seq', (source, cursor)))
    with cache.lock:
        candidates = [(key, value) for key, value in cache.histories.items()
                      if key[0] == source and key[1] <= cursor and positions[:len(value[0])] == value[0]]
        prior = max(candidates, key=lambda item: item[0][1])[1] if candidates else ((), ())
    after = prior[0][-1][0] if prior[0] else 0
    rows = prior[1]
    if len(positions) != len(prior[0]):
        rows += tuple(loads(row[0]) for row in conn.execute(
            'SELECT payload FROM events WHERE task_id=? AND seq>? AND seq<=? ORDER BY seq',
            (source, after, cursor)))
    with cache.lock:
        cache.histories[source, cursor] = (positions, rows)
        cache.histories.move_to_end((source, cursor))
        while len(cache.histories) > 16 or sum(len(v[1]) for v in cache.histories.values()) > 50_000:
            cache.histories.popitem(last=False)
    return rows


def folded_events(application, source, events, advance, initial):
    """Resume a deterministic accumulator at the nearest compatible checkpoint."""
    cache = cache_for(application)
    positions = tuple((event['seq'], event['event_id']) for event in events)
    with cache.lock:
        candidates = [value for key, value in cache.folds.items() if key[0] == source
                      and len(value[0]) <= len(positions) and positions[:len(value[0])] == value[0]]
        prior = max(candidates, key=lambda value: len(value[0])) if candidates else ((), initial)
        state = deepcopy(prior[1])
    for event in events[len(prior[0]):]:
        advance(state, event)
    cursor = events[-1]['seq'] if events else 0
    with cache.lock:
        cache.folds[source, cursor] = (positions, deepcopy(state))
        cache.folds.move_to_end((source, cursor))
        while len(cache.folds) > 16 or sum(len(v[0]) for v in cache.folds.values()) > 50_000:
            cache.folds.popitem(last=False)
    return state
