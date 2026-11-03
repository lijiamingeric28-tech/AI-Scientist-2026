"""Select an exact native key without changing the returned identity evidence."""
from astroquery_ai.runtime.errors import DomainError
from .catalogs import gaia_global_designation, declared_namespace, local_identifier


def save_query_observation(repository, conn, task_id, key, version, outcome):
    """A cache-consumption receipt must not change an immutable source observation."""
    from astroquery_ai.runtime.codec import digest, content_hash
    reuse = outcome.get('raw_response_reused_from')
    body = {k: v for k, v in outcome.items() if k != 'raw_response_reused_from'}
    try:
        previous = repository.object(conn, task_id, 'catalog_identity_query', key, version)
    except DomainError as exc:
        if exc.code != 'OBJECT_NOT_FOUND':
            raise
        reference = repository.put_object(conn, task_id, 'catalog_identity_query', key, version, body)
    else:
        if {k: v for k, v in previous.items() if k != 'raw_response_reused_from'} != body:
            raise DomainError('IDENTITY_QUERY_OBSERVATION_CHANGED', '同一原始查询观察内容改变，不能覆盖已保存版本',
                              object_id=key, version=version)
        reference = {'id': key, 'version': version, 'content_sha256': content_hash(previous)}
    if reuse:
        receipt = {'query_observation_ref': reference, 'reused_response_ref': reuse,
                   'job_id': outcome['job_id'], 'source_bytes_changed': False}
        repository.put_object(conn, task_id, 'catalog_response_reuse', 'reuse-' + digest(receipt), 1, receipt)
    return reference


def cached_identity_response(repository, conn, task_id, table_id, query):
    """First actual response in this frozen task, shared by column partitions.

    Raw rows are reused, never a model's interpretation or a different task's
    measurements. Every consumer still rechecks returned schema and identity.
    The existing three-HTTP-attempt limit is unchanged.
    """
    from astroquery_ai.runtime.codec import loads
    keys = ('query_column', 'selector', 'datatype')
    rows = conn.execute("SELECT object_id,version,content_sha256,payload FROM objects WHERE task_id=? AND kind='catalog_identity_query' ORDER BY created_at,object_id,version", (task_id,))
    for row in rows:
        item = loads(row['payload'])
        prior = item.get('query_execution', {})
        if (item.get('table_id') == table_id and item.get('response_artifact')
                and item.get('response_metadata', {}).get('status') == 200
                and all(prior.get(k) == query.get(k) for k in keys)):
            return {**item, 'cache_record_ref': {'id': row['object_id'], 'version': row['version'],
                                               'content_sha256': row['content_sha256']}}
    return None


def identifier_query(table, planned_column, namespace, selector):
    column = next(c for c in table['columns'] if c['name'] == planned_column)
    result = {'query_column': planned_column, 'selector': selector, 'datatype': column.get('datatype'),
        'planned_column': planned_column, 'namespace': namespace, 'rule': 'declared_exact_key',
        'matched_returned_column_required': planned_column}
    if not (namespace and namespace.casefold().startswith('gaia ') and gaia_global_designation(column)):
        return result
    candidates = []
    for other in table['columns']:
        if (other.get('datatype') not in {'unsignedByte', 'short', 'int', 'long'}
                or not {'meta.id', 'meta.main'} <= set((other.get('ucd') or '').split(';'))):
            continue
        try:
            actual = declared_namespace(other, None, table_metadata=table)
        except DomainError:
            continue
        if actual and actual.casefold() == namespace.casefold():
            candidates.append(other)
    local = local_identifier(selector, namespace)
    if len(candidates) == 1 and local is not None and local.isdecimal():
        result.update(query_column=candidates[0]['name'], selector=local, datatype=candidates[0]['datatype'],
            rule='gaia_global_designation_to_declared_native_id_1',
            basis='https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html#designation')
    return result
