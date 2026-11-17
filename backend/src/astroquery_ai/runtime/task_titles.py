"""Read-only title provenance for old and current tasks; no history rewrite."""
from .codec import loads


def title_origin(conn, task):
    tid = task['task_id']
    renamed = conn.execute("SELECT 1 FROM events WHERE task_id=? AND "
        "json_extract(CAST(payload AS TEXT),'$.kind')='task_title_updated' LIMIT 1", (tid,)).fetchone()
    if renamed:
        return 'custom'
    if task.get('kind') == 'replay':
        snapshot = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='replay_snapshot' "
                                "ORDER BY version DESC LIMIT 1", (tid,)).fetchone()
        if snapshot:
            return loads(snapshot[0]).get('source_view', {}).get('title_origin', 'custom')
    messages = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='message' "
                            "ORDER BY created_at,object_id,version", (tid,))
    question = next((m['text'] for row in messages if (m := loads(row[0])).get('original')
                     and m.get('role') == 'user' and isinstance(m.get('text'), str)), None)
    if question is None and task.get('query_ref'):
        ref = loads(task['query_ref']) if isinstance(task['query_ref'], str) else task['query_ref']
        row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='confirmed_query' "
                           "AND object_id=? AND version=?", (tid, ref['id'], ref['version'])).fetchone()
        question = loads(row[0]).get('original_query') if row else None
    title = task.get('title')
    return 'auto' if question is not None and title in (question, question[:120]) else 'custom'
