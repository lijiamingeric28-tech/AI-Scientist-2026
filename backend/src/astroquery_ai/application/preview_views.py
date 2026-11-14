"""Page/evidence-bound enrichment for the existing read-only preview route."""
from astroquery_ai.science.evidence_views import build_views


_LATEST = ("o.task_id=? AND o.kind=? AND o.version=(SELECT max(i.version) FROM objects i "
           "WHERE i.task_id=o.task_id AND i.kind=o.kind AND i.object_id=o.object_id)")


def _objects_matching(repository, conn, task_id, kind, values, *, json_path=None):
    """Filter latest identities in SQLite before decoding selected payloads."""
    if not values:
        return []
    column = 'json_extract(CAST(o.payload AS TEXT),?)' if json_path else 'o.object_id'
    args = [task_id, kind, *([json_path] if json_path else []), *sorted(values)]
    identities = conn.execute('SELECT o.object_id,o.version FROM objects o WHERE ' + _LATEST +
        ' AND ' + column + ' IN (' + ','.join('?' for _ in values) + ') ORDER BY o.object_id', args)
    return [repository.object(conn, task_id, kind, row[0], row[1]) for row in identities]


class _EvidenceReadScope:
    """Supply build_views only the latest objects relevant to this page's evidence.

    Table selections include interpretations of *every* measurement referencing
    the displayed evidence, even when those measurements are on another page.
    Only their reference metadata is needed; full measurements are not decoded.
    """
    def __init__(self, repository, conn, task_id, evidence):
        self.repository, self.conn, self.task_id = repository, conn, task_id
        self.tables = {e['evidence_id'] for e in evidence if e.get('text_origin') == 'original_cells'}
        papers = [e for e in evidence if e.get('locator', {}).get('page') and e.get('artifact_ref')]
        self.shas = {e['artifact_ref']['content_sha256'] for e in papers}
        self.artifact_ids = {e['artifact_ref']['id'] for e in papers}
        self.records = None

    def objects(self, conn, task_id, kind):
        if conn is not self.conn or task_id != self.task_id:
            raise ValueError('preview evidence read scope mismatch')
        if kind == 'measurement':
            if self.records is None:
                self.records = []
                if self.tables:
                    references = conn.execute(
                        "SELECT json_extract(e.value,'$.id'),"
                        "json_extract(CAST(o.payload AS TEXT),'$.interpretation_ref.id') "
                        "FROM objects o JOIN json_each(CAST(o.payload AS TEXT),'$.evidence_refs') e "
                        'WHERE ' + _LATEST + " AND json_extract(e.value,'$.id') IN (" +
                        ','.join('?' for _ in self.tables) + ') ORDER BY o.object_id',
                        [task_id, 'measurement', *sorted(self.tables)])
                    self.records = [{'evidence_refs': [{'id': row[0]}], 'interpretation_ref': {'id': row[1]}}
                                    for row in references]
            return self.records
        if kind == 'interpretation':
            ids = {r['interpretation_ref']['id'] for r in self.objects(conn, task_id, 'measurement')
                   if r['interpretation_ref']['id'] is not None}
            return _objects_matching(self.repository, conn, task_id, kind, ids)
        if kind == 'document_index':
            return _objects_matching(self.repository, conn, task_id, kind, self.shas, json_path='$.sha256')
        if kind == 'evidence_page_preview':
            return _objects_matching(self.repository, conn, task_id, kind, self.artifact_ids, json_path='$.pdf_artifact_id')
        raise ValueError('unsupported preview evidence collection')


def enrich_preview_page(repository, conn, task_id, rows):
    evidence = {e['evidence_id']: {'source_id': row['source_document']['source_id'], **e}
                for row in rows for e in row['evidence']}
    sources = {row['source_document']['source_id']: row['source_document'] for row in rows}
    scope = _EvidenceReadScope(repository, conn, task_id, list(evidence.values()))
    views = build_views(scope, conn, task_id, list(evidence.values()), list(sources.values()))
    mids = {row['source']['measurement_id'] for row in rows}
    # Keep the former latest-per-object and object-ID ordering when several
    # saved processing objects refer to one measurement.
    derived = {d['measurement_id']: d for d in _objects_matching(
        repository, conn, task_id, 'derived', mids, json_path='$.measurement_id')}
    for row in rows:
        ids = {e['evidence_id'] for e in row['evidence']}
        row['evidence_views'] = [view for view in views if view['evidence_id'] in ids]
        row['saved_processing'] = derived.get(row['source']['measurement_id'])
