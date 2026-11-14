"""Disposable, exact-version UI index. Nothing here grants execution authority."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock

from astroquery_ai.application.result_filters import (
    normalize_filters, record_coordinates, search_fields, source_group, source_year, sql_predicate,
)
from astroquery_ai.runtime.codec import canonical, digest


PROJECTION_PROTOCOL = 'delivery-list/4'
_LOCKS = [RLock() for _ in range(64)]
_DATABASE_LOCK = RLock()


def _schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rows (
          key TEXT NOT NULL, position INTEGER NOT NULL, record_id TEXT, source_id TEXT,
          field TEXT, property_id TEXT, year REAL, search_text TEXT, source_group TEXT,
          excluded INTEGER, modified INTEGER, duplicate INTEGER, group_key TEXT, payload TEXT NOT NULL,
          PRIMARY KEY(key,position));
        CREATE INDEX IF NOT EXISTS rows_record ON rows(key,record_id);
        CREATE INDEX IF NOT EXISTS rows_source ON rows(key,source_id);
        CREATE INDEX IF NOT EXISTS rows_field ON rows(key,field);
    ''')


def _year(source, sid):
    try:
        value = float(source_year(source) or 0)
        if value and value == value:
            return value
    except (ValueError, TypeError):
        pass
    match = re.match(r'^\d{4}', sid or '')
    return int(match[0]) if match else None


def _entry_rows(rows, resource):
    for position, row in enumerate(rows):
        if resource == 'records':
            record = record_coordinates(row) if 'property_binding' in row else row
            source = row.get('source_label') or {}
        else:
            source = row
            record = {'record_id': row['source_id'], 'source_id': row['source_id']}
        flags = row.get('flags') or {}
        group = row.get('duplicate_group') or {}
        # Definitions and citation labels are stored once per pinned entry;
        # only this page's references are expanded at the response boundary.
        payload = row
        if resource == 'records':
            payload = {k: v for k, v in row.items() if k not in {'source_label', 'property_binding'}}
            if 'property_binding' in row:
                payload['_binding_id'] = row['property_binding']['property_id']
        yield (position, record['record_id'], record['source_id'], record.get('field_name'),
            record.get('property_id'), _year(source, record['source_id']), search_fields(record, source),
            source_group(source, record.get('extraction_method')), int(flags.get('excluded', False)),
            int(flags.get('modified', False)), int(flags.get('duplicate', False)),
            group.get('group_id') if group.get('archive') else None, canonical(payload).decode())


class ResultReadIndex:
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def matching_ids(cls, rows, filters):
        """Commands reuse predicates, but rebuild from their authoritative snapshot."""
        filters = normalize_filters(filters)
        with closing(sqlite3.connect(':memory:')) as conn:
            _schema(conn)
            cls._build(conn, 'selection', lambda: (rows, {'resource': 'records'}))
            return cls._query(conn, 'selection', filters, 0, 1, False, True)

    def _connect(self):
        with _DATABASE_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=15)
            try:
                _schema(conn)
            except sqlite3.DatabaseError as error:
                conn.close()
                if isinstance(error, sqlite3.OperationalError):
                    raise
                # This exact path is a disposable cache, never the runtime DB.
                self.path.unlink(missing_ok=True)
                conn = sqlite3.connect(self.path, timeout=15)
                _schema(conn)
            return conn

    @staticmethod
    def _build(conn, key, builder):
        rows, metadata = builder()
        resource = metadata['resource']
        if resource == 'records':
            metadata = {**metadata, '_bindings': {r['property_binding']['property_id']: r['property_binding']
                        for r in rows if 'property_binding' in r}}
        # A complete marker and every row become visible in one transaction.
        with conn:
            conn.execute('DELETE FROM rows WHERE key=?', (key,))
            conn.executemany('INSERT INTO rows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             ((key, *row) for row in _entry_rows(rows, resource)))
            conn.execute('INSERT OR REPLACE INTO entries VALUES(?,?)',
                         (key, canonical({**metadata, '_row_count': len(rows)}).decode()))

    @staticmethod
    def _query(conn, key, filters, offset, limit, collapse, ids_only):
        entry = conn.execute('SELECT metadata FROM entries WHERE key=?', (key,)).fetchone()
        if not entry:
            return None
        metadata = json.loads(entry[0])
        row_count = conn.execute('SELECT count(*) FROM rows WHERE key=?', (key,)).fetchone()[0]
        if metadata.pop('_row_count', None) != row_count:
            return None
        where, args = sql_predicate(filters)
        clause = 'key=? AND ' + where
        args = [key, *args]
        total = conn.execute('SELECT count(*) FROM rows WHERE ' + clause, args).fetchone()[0]
        order = 'position' if filters['year_sort'] == 'none' else (
            'year IS NULL, year ' + filters['year_sort'] + ', position')
        if ids_only:
            return [row[0] for row in conn.execute('SELECT record_id FROM rows WHERE ' + clause + ' ORDER BY position', args)]
        query = 'SELECT payload FROM rows WHERE ' + clause + ' ORDER BY ' + order
        display_total = total
        if collapse:
            # Rank the filtered/sorted set, preserving the first visible member.
            ranked = ('SELECT payload, position, year, row_number() OVER (PARTITION BY '
                "coalesce(group_key, char(0)||record_id) ORDER BY " + order +
                ') AS rank FROM rows WHERE ' + clause)
            display_total = conn.execute('SELECT count(*) FROM (' + ranked + ') WHERE rank=1', args).fetchone()[0]
            query = 'SELECT payload FROM (' + ranked + ') WHERE rank=1 ORDER BY ' + order
        items = [json.loads(row[0]) for row in conn.execute(query + ' LIMIT ? OFFSET ?', [*args, limit, offset])]
        labels = metadata.pop('source_labels', {})
        bindings = metadata.pop('_bindings', {})
        if metadata['resource'] == 'records':
            for item in items:
                if '_binding_id' in item:
                    item['property_binding'] = bindings[item.pop('_binding_id')]
                    sid = item['source']['source_ref']['id']
                else:
                    sid = item.get('source_id')
                item['source_label'] = labels.get(sid, {'source_id': sid})
        global_counts = conn.execute('SELECT count(*),coalesce(sum(excluded),0),coalesce(sum(modified),0),'
            'coalesce(sum(duplicate),0) FROM rows WHERE key=?', (key,)).fetchone()
        base_where, base_args = sql_predicate({'quick': filters['quick']})
        fields = [{'field': f, 'property_id': p, 'count': n} for f, p, n in conn.execute(
            'SELECT field,property_id,count(*) FROM rows WHERE key=? AND ' + base_where +
            ' GROUP BY field,property_id ORDER BY min(position)', [key, *base_args]) if f is not None]
        sources = [{**labels.get(sid, {'source_id': sid}), 'count': count} for sid, count in conn.execute(
            'SELECT source_id,count(*) FROM rows WHERE key=? AND ' + base_where +
            ' GROUP BY source_id ORDER BY min(position)', [key, *base_args])]
        return {**metadata, 'items': items, 'total': total, 'display_total': display_total,
                'offset': offset, 'limit': limit,
                'aggregates': dict(zip(('total', 'owner_excluded', 'modified', 'duplicate'), global_counts),
                                   fields=fields, sources=sources)}

    def read(self, identity, builder, *, filters=None, offset=0, limit=100,
             collapse_duplicates=False, ids_only=False):
        filters = normalize_filters(filters)
        offset, limit = max(0, offset), min(500, max(1, limit))
        key = digest([*identity, PROJECTION_PROTOCOL])
        lock = _LOCKS[int(key[:8], 16) % len(_LOCKS)]
        with lock:
            try:
                with closing(self._connect()) as conn:
                    try:
                        result = self._query(conn, key, filters, offset, limit, collapse_duplicates, ids_only)
                    except (ValueError, KeyError, TypeError):
                        result = None  # Invalid cached JSON/metadata is a miss.
                    if result is None:
                        self._build(conn, key, builder)
                        result = self._query(conn, key, filters, offset, limit, collapse_duplicates, ids_only)
                    return result
            except (sqlite3.Error, OSError):
                # An unavailable cache cannot turn an existing delivery into an
                # empty result or fail publication. Use the same predicates.
                with closing(sqlite3.connect(':memory:')) as conn:
                    _schema(conn)
                    self._build(conn, key, builder)
                    return self._query(conn, key, filters, offset, limit, collapse_duplicates, ids_only)
