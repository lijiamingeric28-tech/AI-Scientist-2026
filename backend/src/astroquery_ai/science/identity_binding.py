"""Evidence for an actual returned identifier, independent of column semantics."""
from astroquery_ai.runtime.codec import digest, content_hash
from astroquery_ai.runtime.errors import DomainError
from .catalogs import exact_rows, exact_identifier, local_identifier, gaia_global_designation
from .table_metadata import coordinate_groups
from .identity_consistency import row_identifier_conflicts


def exact_binding(target, table, rows, matches, id_column, namespace, artifact, *, source_rows=None, response_sha256=None, query_execution=None):
    aliases = [target['main_id'], *target.get('aliases', [])]
    checked = set(exact_rows(rows, [id_column], aliases, {id_column: namespace} if namespace else None))
    if not set(matches) <= checked or not matches:
        raise DomainError('IDENTITY_BINDING_UNVERIFIED_ROWS', '匹配凭据包含未经核验的行')
    if any(row_identifier_conflicts(target, table, rows[i]) for i in matches):
        raise DomainError('IDENTITY_BINDING_CONFLICTING_KEYS', '返回行的多个已声明标识存在身份冲突')
    if source_rows is not None and len(source_rows) != len(rows):
        raise DomainError('IDENTITY_BINDING_ROW_LAYOUT', '原行定位与实际返回行不一致')
    alias_keys = {exact_identifier(a): a for a in aliases}
    keys = []
    astrometry = coordinate_groups(table)
    coordinate_columns = {c['name'] for group in astrometry['coordinate_groups']
                          for candidates in group['columns'].values() for c in candidates}
    for index in matches:
        original = rows[index][id_column]
        value = original
        if namespace and local_identifier(value, namespace) is None:
            value = namespace + ' ' + value.strip()
        normalized = exact_identifier(value)
        keys.append({'response_row': index, 'source_row': source_rows[index] if source_rows else index,
                     'value': original, 'matched_target_alias': alias_keys[normalized],
                     'actual_coordinate_cells': {name: rows[index].get(name) for name in sorted(coordinate_columns)},
                     'actual_time_cells': {c['column']: rows[index].get(c['column']) for c in astrometry['time_columns']}})
    result = {'schema_version': 'ExactIdentifierBinding/1', 'method': 'exact_id',
        'target_id': target['target_id'], 'table_id': table['table_id'], 'id_column': id_column, 'namespace': namespace,
        'target_content_sha256': content_hash(target),
        'column_metadata': next(c for c in table['columns'] if c['name'] == id_column),
        'table_namespace_evidence': {k: table.get(k) for k in ('table_id', 'description', 'resource_description')},
        'actual_returned_keys': keys, 'source_rows': [k['source_row'] for k in keys],
        'source_artifact_ref': {'id': artifact['artifact_id'], 'version': 1, 'content_sha256': artifact['sha256']},
        'source_response_hash': response_sha256 or artifact['sha256'],
        'verified_target_aliases': aliases, 'normalization_rule': 'exact-namespace-preserving-3',
        'relation': 'same_entity_identifier_anchor', 'measurement_subject_validation_required': True,
        'table_astrometry_context': astrometry,
        'substring_matching': False}
    if query_execution:
        result['query_execution'] = {**query_execution, 'actual_returned_query_keys': [
            {'response_row': index, 'value': rows[index].get(query_execution['query_column'])} for index in matches]}
    if namespace and namespace.casefold() == '2mass':
        result['namespace_syntax_basis'] = {'rule': '2mass-psc-prefix-1', 'suffixes_preserved': True,
            'source': 'https://cdsarc.cds.unistra.fr/ftp/cats/II/246/ReadMe', 'locator': 'Note (1)'}
    if namespace and namespace.casefold().startswith('gaia ') and gaia_global_designation(result['column_metadata']):
        result['namespace_syntax_basis'] = {'rule': 'gaia-global-designation-1', 'release_prefix_preserved': True,
            'source': 'https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html',
            'locator': 'designation and source_id'}
    result['binding_id'] = 'exact-id-' + digest(result)
    return result
