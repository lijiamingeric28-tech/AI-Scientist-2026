"""Commit one current representation through the existing repository transaction."""
from .codec import loads
from .errors import DomainError


def commit_current_representation(repo, conn, task_id, record, result, *, job=None):
    current = repo.object(conn, task_id, 'measurement', record['measurement_id'])
    if (current['content_sha256'] != record['content_sha256']
            or result['source_representation_hash'] != record['content_sha256']):
        raise DomainError('NORMALIZATION_SOURCE_CHANGED', '处理回执不能覆盖更新后的来源解释')
    query = loads(repo.task(conn, task_id)['query_ref'])
    spec = repo.object(conn, task_id, 'confirmed_query', query['id'], query['version'])
    output = next(b['output_profile'] for b in spec['properties'] if b['property_id'] == record['property_ref']['id'])
    expected = {'id': output['profile_id'], 'version': output['version'], 'content_sha256': output['content_sha256']}
    if result.get('output_profile_ref') != expected:
        raise DomainError('DERIVED_OUTPUT_PROFILE_CHANGED', '派生结果不属于冻结输出配置')
    reference = repo.put_object(conn, task_id, 'derived', result['derived_id'], 1, result)
    selection = {'measurement_id': record['measurement_id'], 'source_hash': record['content_sha256'],
                 'output_profile_ref': expected, 'derived_ref': reference}
    prior = next((p for p in repo.objects(conn, task_id, 'derived_current') if p['measurement_id'] == record['measurement_id']), None)
    if prior != selection:
        version = conn.execute("SELECT coalesce(max(version),0)+1 FROM objects WHERE task_id=? AND kind='derived_current' AND object_id=?", (task_id, record['measurement_id'])).fetchone()[0]
        repo.put_object(conn, task_id, 'derived_current', record['measurement_id'], version, selection)
    from .normalization_receipts import record_normalization_outcome
    record_normalization_outcome(repo, conn, task_id, record, output, result, reference, job)
    return reference
