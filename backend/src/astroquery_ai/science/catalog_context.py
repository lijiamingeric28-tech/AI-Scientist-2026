"""Bound complete field groups, never truncate scientific descriptions to fit."""
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from .prompt_contracts import table_view


MAX_HEADER_BYTES = 46000  # Complete TP52 definitions; room below the 48K message bound.


def visible_columns(prompt):
    view = prompt['table']
    index = view['column_attributes'].index('name')
    return {row[index] for row in view['columns']}


def mapping_fields(mapping):
    names = {mapping['value_column']}
    for key in ('error_columns', 'context_columns', 'quality_columns', 'reference_columns'):
        names.update(mapping.get(key, []))
    if mapping.get('limit_column'):
        names.add(mapping['limit_column'])
    return names


def associated_columns(table, selected):
    """Literal CDS-style name groups are hints; their roles still need metadata."""
    return {c['name'] for c in table['columns'] if '_' in c['name']
        and c['name'].split('_', 1)[0].lower() in {'e', 'l', 'r', 'q', 'f', 'n', 'o'}
        and c['name'].split('_', 1)[1] in selected}


def retain_declared_errors(plan, table):
    """An exact name association AND explicit stat.error preserve source raw errors.

    This does not assign sigma, confidence, stat/sys, units or numeric meaning.
    """
    checks, mappings = [], []
    for mapping in plan['properties']:
        declared = [c['name'] for c in table['columns'] if c['name'] in {
            'e_' + mapping['value_column'], 'E_' + mapping['value_column']}
            and 'stat.error' in (c.get('ucd') or '').split(';')]
        missing = [name for name in declared if name not in mapping['error_columns']]
        mappings.append({**mapping, 'error_columns': [*mapping['error_columns'], *missing]})
        checks.extend({'value_column': mapping['value_column'], 'error_column': name,
            'state': 'source_declared_error_raw_retention', 'semantic_interpretation_granted': False} for name in missing)
    return {**plan, 'properties': mappings}, checks


def required_fields(plan):
    return ({plan['id_column']} if plan['id_column'] else set()).union(
        *(mapping_fields(m) for m in plan['properties']))


def bounded_header(prompt, table, targets=None, *, required=()):
    """Use full metadata when possible, otherwise an index plus complete local fields.

    The index is a navigation aid, never evidence for an unseen column's meaning.
    A proposed remote dependency requires the one shared follow-up before use.
    """
    if len(canonical(prompt)) <= MAX_HEADER_BYTES and not required:
        return prompt
    selected = set(targets or [c['name'] for c in table['columns']]) | set(required)
    # Literal field references in the frozen definitions are navigation hints,
    # never a mapping or a provider whitelist. Supply their actual metadata on
    # the first read (for example a separate timing-scale/epoch column), rather
    # than spending the only shared follow-up discovering an already named key.
    from .catalog_document import _referenced_names
    selected.update(_referenced_names(tuple(c['name'] for c in table['columns']),
                                     canonical(prompt.get('properties', [])).decode()))
    selected.update(associated_columns(table, selected))
    for column in table['columns']:
        if 'meta.id' in (column.get('ucd') or '').split(';'):
            selected.add(column['name'])
    if table.get('catalog_document'):
        from .catalog_document import document_view
        doc = document_view(table['catalog_document'], selected, [c['name'] for c in table['columns']])
        selected.update(doc['referenced_column_names'])
    compact = {**prompt, 'table': table_view(table, selected),
        'column_index': [c['name'] for c in table['columns']],
        'metadata_visibility': {
            'complete_columns': sorted(selected),
            'index_only_columns_are_not_semantic_evidence': True,
            'rule': 'Only complete columns have been read. If an index-only field is needed, reference its exact name in the proposed group; software must supply its full metadata in the single shared follow-up before that mapping can be used. Never assume an unseen error, flag or reference has no effect.',
        }}
    if len(canonical(compact)) > MAX_HEADER_BYTES:
        raise DomainError('CATALOG_CONTEXT_REQUIRES_PARTITION', '完整列说明和性质定义超出本次输入上界，必须在收费前缩批')
    return compact


def planned_partitions(table, spec, prompt_factory):
    """Pre-dispatch partition; failures never create fresh paid-attempt roots."""
    columns = [c['name'] for c in table['columns']]
    pending = [(columns, spec['properties'])]
    result, gaps = [], []
    while pending:
        targets, bindings = pending.pop(0)
        try:
            prompt_factory(table, {**spec, 'properties': bindings}, targets)
        except DomainError as exc:
            if exc.code != 'CATALOG_CONTEXT_REQUIRES_PARTITION':
                raise
            # A large shared definition cannot be repaired by splitting every
            # column first: that creates N single-field roots and can still
            # reject an entire property. Split independent definitions first.
            if len(bindings) > 1:
                middle = len(bindings) // 2
                pending[0:0] = [(targets, bindings[:middle]), (targets, bindings[middle:])]
            elif len(targets) > 1:
                middle = len(targets) // 2
                pending[0:0] = [(targets[:middle], bindings), (targets[middle:], bindings)]
            else:
                gaps.append({'target_columns': targets, 'property_ids': [b['property_id'] for b in bindings],
                    'reason': 'single_complete_field_definition_exceeds_input_bound', 'paid_calls': 0})
        else:
            result.append({'target_columns': targets, 'property_ids': [b['property_id'] for b in bindings]})
    return result, gaps


def quarantine_unseen(plan, visible):
    """An unprovided dependency affects its own group, not its valid siblings."""
    gaps, kept = [], []
    for mapping in plan['properties']:
        missing = mapping_fields(mapping) - visible
        if plan['id_column'] is not None and plan['id_column'] not in visible:
            missing.add(plan['id_column'])
        if missing:
            gaps.append({'property_id': mapping['property_id'], 'value_column': mapping['value_column'],
                'reason': 'required_field_metadata_not_read', 'columns': sorted(missing)})
        else:
            kept.append(mapping)
    return {**plan, 'properties': kept}, gaps
