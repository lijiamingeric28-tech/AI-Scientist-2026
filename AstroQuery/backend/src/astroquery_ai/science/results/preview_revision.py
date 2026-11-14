"""Cheap content dependencies shared by state hints and provisional paging.

Object hashes are immutable repository facts. Reading their identities avoids
materializing scientific records merely to decide whether to refresh a page.
Keep this list aligned with publication.preview and evidence_views.build_views.
"""
from astroquery_ai.runtime.codec import digest


DEPENDENCY_KINDS = (
    'confirmed_query', 'measurement', 'candidate', 'admission_disposition',
    'derived', 'derived_current', 'current_representation', 'normalization_outcome',
    'evidence', 'context', 'source', 'source_statement', 'document_index',
    'evidence_page_preview', 'interpretation',
)


def preview_revision(conn, task):
    if task['kind'] in {'legacy', 'replay'} or task['science_state'] == 'sealed' or not task['query_ref']:
        return None
    tid = task['task_id']
    placeholders = ','.join('?' for _ in DEPENDENCY_KINDS)
    objects = [list(row) for row in conn.execute(
        f'SELECT kind,object_id,version,content_sha256 FROM objects WHERE task_id=? '
        f'AND kind IN ({placeholders}) ORDER BY kind,object_id,version',
        (tid, *DEPENDENCY_KINDS))]
    reviews = [[v.decode() if isinstance(v, bytes) else v for v in row] for row in conn.execute(
        'SELECT review_id,revision,basis_hash,status,payload,answer,application '
        'FROM reviews WHERE task_id=? ORDER BY review_id', (tid,))]
    artifacts = [list(row) for row in conn.execute(
        'SELECT a.artifact_id,a.sha256,a.availability,r.owner_id FROM artifact_refs r '
        'JOIN artifacts a ON a.artifact_id=r.artifact_id WHERE r.task_id=? '
        'ORDER BY a.artifact_id,r.owner_id', (tid,))]
    return 'preview-v2-' + digest({
        'protocol': 2, 'task_id': tid, 'query_ref': task['query_ref'],
        'generation': task['generation'], 'objects': objects, 'reviews': reviews, 'artifacts': artifacts,
    })
