'Check independent declared identifier columns before claiming a source row.'

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.science.catalog.identifiers import declared_namespace, local_identifier, exact_identifier

def row_identifier_conflicts(target, table, row):
    conflicts = []
    aliases = [target['main_id'], *target.get('aliases', [])]
    for column in table['columns']:
        if not any((term == 'meta.id' or term.startswith('meta.id.') for term in (column.get('ucd') or '').split(';'))):
            continue
        try:
            namespace = declared_namespace(column, None, table_metadata=table)
        except DomainError:
            continue
        if namespace is None:
            continue
        expected = {exact_identifier(a) for a in aliases if local_identifier(a, namespace) is not None}
        value = row.get(column['name'])
        if not expected or not isinstance(value, str) or (not value.strip()) or (value == column.get('null')):
            continue
        full = value if local_identifier(value, namespace) is not None else namespace + ' ' + value.strip()
        try:
            actual = exact_identifier(full)
        except DomainError:
            continue
        if actual not in expected:
            conflicts.append({'column': column['name'], 'namespace': namespace, 'actual_returned_key': value, 'target_aliases_in_namespace': [a for a in aliases if local_identifier(a, namespace) is not None], 'reason': 'declared_identifier_conflicts_with_target_alias', 'column_metadata': column})
    return conflicts
