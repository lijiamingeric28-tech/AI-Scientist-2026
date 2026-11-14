"""Normalized, disposable display data in the existing UI cache database.

The caller must validate the authoritative publication before every read. Only
completed transactions are usable; no cached value is an execution authority.
"""
from contextlib import closing
from hashlib import sha256
import json
import sqlite3
from threading import RLock

from astroquery_ai.runtime.codec import canonical, digest


PROTOCOL = 'delivery-detail/5'
# List misses enter this index while holding a list stripe. Sharing their
# pool can reverse two publications' lock order; projection stripes are private.
_PROJECTION_LOCKS = [RLock() for _ in range(64)]


class CacheMiss(Exception):
    pass


def schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS delivery_projections (
            key TEXT PRIMARY KEY, item_count INTEGER NOT NULL, value_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS delivery_items (
            key TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, position INTEGER NOT NULL,
            payload BLOB NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(key,kind,id));
        CREATE INDEX IF NOT EXISTS delivery_items_order ON delivery_items(key,kind,position);
        CREATE TABLE IF NOT EXISTS delivery_values (
            key TEXT NOT NULL, id TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(key,id));
    ''')


class ProjectionReader:
    def __init__(self, conn, key):
        self.conn, self.key = conn, key

    def _decode(self, raw, expected):
        if sha256(raw).hexdigest() != expected:
            raise CacheMiss()
        return json.loads(raw)

    def _expand(self, row):
        item = self._decode(row[0], row[1])
        def value(ref):
            row = self.conn.execute('SELECT payload FROM delivery_values WHERE key=? AND id=?',
                                    (self.key, ref)).fetchone()
            if not row:
                raise CacheMiss()
            return self._decode(row[0], ref)
        result = item['own']
        for field, refs in item['refs'].items():
            result[field] = [value(ref) for ref in refs[1]] if refs[0] == 'list' else value(refs[1])
        return result

    def get(self, kind, identifier=''):
        row = self.conn.execute('SELECT payload,sha FROM delivery_items WHERE key=? AND kind=? AND id=?',
                                (self.key, kind, identifier)).fetchone()
        return self._expand(row) if row else None

    def rows(self, kind, *, offset=0, limit=None):
        query = 'SELECT payload,sha FROM delivery_items WHERE key=? AND kind=? ORDER BY position'
        args = [self.key, kind]
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            args.extend((limit, offset))
        return [self._expand(row) for row in self.conn.execute(query, args)]

    def count(self, kind):
        return self.conn.execute('SELECT count(*) FROM delivery_items WHERE key=? AND kind=?',
                                 (self.key, kind)).fetchone()[0]

    def selected(self, kind, identifiers):
        identifiers = list(dict.fromkeys(identifiers))
        if not identifiers:
            return []
        marks = ','.join('?' for _ in identifiers)
        query = ('SELECT payload,sha FROM delivery_items WHERE key=? AND kind=? AND id IN (' + marks +
                 ') ORDER BY position')
        return [self._expand(row) for row in self.conn.execute(query, [self.key, kind, *identifiers])]


class DeliveryProjectionIndex:
    def __init__(self, list_index):
        self.list_index = list_index

    def read_existing(self, identity, select):
        """Optional narrow fast path; never build an unrelated full projection."""
        from astroquery_ai.runtime.result_index import PROJECTION_PROTOCOL
        key = digest([*identity, PROTOCOL, PROJECTION_PROTOCOL])
        with _PROJECTION_LOCKS[int(key[:8], 16) % len(_PROJECTION_LOCKS)]:
            try:
                with closing(self.list_index._connect()) as conn:
                    schema(conn)
                    if self._valid(conn, key):
                        return select(ProjectionReader(conn, key))
            except (sqlite3.Error, OSError, CacheMiss, ValueError, KeyError, TypeError):
                pass
        return None

    @staticmethod
    def _valid(conn, key):
        marker = conn.execute('SELECT item_count,value_count FROM delivery_projections WHERE key=?', (key,)).fetchone()
        return marker and tuple(marker) == (
            conn.execute('SELECT count(*) FROM delivery_items WHERE key=?', (key,)).fetchone()[0],
            conn.execute('SELECT count(*) FROM delivery_values WHERE key=?', (key,)).fetchone()[0])

    @staticmethod
    def _build(conn, key, builder):
        # Memoize by object identity only during construction. A large evidence
        # object shared by thousands of measurements is serialized exactly once.
        values, memo = {}, {}
        value_batch, item_batch = [], []
        batch_bytes = 0
        def flush():
            nonlocal batch_bytes
            conn.executemany('INSERT INTO delivery_values VALUES(?,?,?)', value_batch)
            conn.executemany('INSERT INTO delivery_items VALUES(?,?,?,?,?,?)', item_batch)
            value_batch.clear()
            item_batch.clear()
            batch_bytes = 0
        def reference(value):
            nonlocal batch_bytes
            address = id(value)
            if address not in memo:
                raw = canonical(value)
                ref = sha256(raw).hexdigest()
                memo[address] = (value, ref)
                if ref not in values:
                    values[ref] = True
                    value_batch.append((key, ref, raw))
                    batch_bytes += len(raw)
                    if len(value_batch) >= 256 or batch_bytes >= 4 * 1024 * 1024:
                        flush()
            return memo[address][1]
        with conn:
            conn.execute('DELETE FROM delivery_projections WHERE key=?', (key,))
            conn.execute('DELETE FROM delivery_items WHERE key=?', (key,))
            conn.execute('DELETE FROM delivery_values WHERE key=?', (key,))
            count = 0
            for position, (kind, identifier, payload) in enumerate(builder()):
                own, refs = {}, {}
                for field, value in payload.items():
                    if isinstance(value, dict):
                        refs[field] = ['value', reference(value)]
                    elif isinstance(value, list):
                        refs[field] = ['list', [reference(item) for item in value]]
                    else:
                        own[field] = value
                raw = canonical({'own': own, 'refs': refs})
                item_batch.append((key, kind, identifier, position, raw, sha256(raw).hexdigest()))
                batch_bytes += len(raw)
                if len(item_batch) >= 256 or batch_bytes >= 4 * 1024 * 1024:
                    flush()
                count += 1
            flush()
            conn.execute('INSERT INTO delivery_projections VALUES(?,?,?)', (key, count, len(values)))

    def read(self, identity, builder, select):
        from astroquery_ai.runtime.result_index import PROJECTION_PROTOCOL
        key = digest([*identity, PROTOCOL, PROJECTION_PROTOCOL])
        with _PROJECTION_LOCKS[int(key[:8], 16) % len(_PROJECTION_LOCKS)]:
            try:
                with closing(self.list_index._connect()) as conn:
                    schema(conn)
                    if self._valid(conn, key):
                        try:
                            return select(ProjectionReader(conn, key))
                        except (CacheMiss, ValueError, KeyError, TypeError):
                            pass
                    self._build(conn, key, builder)
                    return select(ProjectionReader(conn, key))
            except (sqlite3.Error, OSError):
                # A full/unwritable disk must return the same projection. The
                # builder's local snapshot survives this retry, then is released.
                with closing(sqlite3.connect(':memory:')) as conn:
                    schema(conn)
                    self._build(conn, key, builder)
                    return select(ProjectionReader(conn, key))
