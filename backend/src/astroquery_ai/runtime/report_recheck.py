"""Narrow permission for a source owner's read-only report recheck.

Sealed scientific work stays closed. The M11 job may request an existing M06
source check of exact frozen records; it cannot retrieve, extract or mutate
measurements. The ordinary profile authority still authorises the real call.
"""
from .codec import digest, loads


def allowed(repo, conn, task, owner, job, request, root_id, root_limit):
    if (owner != 'M06' or task['science_state'] != 'sealed' or not job
            or job.get('kind') != 'insights' or root_limit > 2
            or request.get('model') != 'qwen3.7-plus' or request.get('enable_thinking') is not False
            or type(request.get('max_tokens')) is not int or request['max_tokens'] > 8192):
        return None
    stored = conn.execute('SELECT owner,kind,task_id,payload FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()
    if (not stored or tuple(stored)[:3] != ('M11', 'insights', task['task_id'])
            or loads(stored['payload']) != job.get('payload')): return None
    query = loads(task['query_ref']) if task['query_ref'] else None
    if not query: return None
    spec = repo.object(conn, task['task_id'], 'confirmed_query', query['id'], query['version'])
    if spec.get('run_policy', {}).get('insights', {}).get('presentation') != 'research-property/1': return None
    delivery_id = job.get('payload', {}).get('delivery_id')
    if not delivery_id: return None
    delivery = repo.object(conn, task['task_id'], 'delivery', delivery_id)
    records = {r['measurement_id']: r for r in delivery['measurements']}
    sources = {s['source_id']: s for s in delivery['sources']}
    message_hash = digest(request.get('messages'))
    for scope in repo.objects(conn, task['task_id'], 'insight_owner_recheck_request'):
        if (scope.get('job_id') != job['job_id'] or scope.get('root_id') != root_id
                or scope.get('delivery_id') != delivery_id
                or scope.get('snapshot_ref') != delivery['snapshot_ref']
                or scope.get('messages_sha256') != message_hash
                or scope.get('purpose') != 'read_only_source_owner_recheck'
                or not scope.get('finding_ids') or not scope.get('measurement_refs')):
            continue
        source = sources.get(scope.get('source_id'))
        if not source or source.get('kind') != 'paper': continue
        valid = True
        for ref in scope['measurement_refs']:
            record = records.get(ref.get('id'))
            if (not record or ref.get('version') != record['revision']
                    or ref.get('content_sha256') != record['content_sha256']
                    or record['source_ref']['id'] != scope['source_id']
                    or record['property_ref']['id'] != scope.get('property_id')):
                valid = False
                break
        if valid: return scope
    return None
