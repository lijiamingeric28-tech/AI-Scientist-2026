"""Preserve source coordinate/time definitions; never infer epoch from equinox."""
from astroquery_ai.runtime.codec import digest


def referenced_context(reference, coordinate_systems, time_systems):
    if not reference:
        return None
    choices = [(kind, item) for kind, items in [('coordinate', coordinate_systems), ('time', time_systems)]
               for item in items if item.get('ID') == reference]
    values = {digest({'kind': kind, 'attributes': {k: v for k, v in item.items() if k != 'ID'}})
              for kind, item in choices}
    if not values:
        return {'state': 'unresolved_reference', 'ref': reference}
    if len(values) != 1:
        return {'state': 'ambiguous_reference', 'ref': reference, 'definitions': [item for _, item in choices]}
    kind, item = choices[0]
    return {'state': 'known', 'kind': kind, 'attributes': {k: v for k, v in item.items() if k != 'ID'}}


def coordinate_groups(table):
    """Describe coordinate solutions and observation times without accepting a match."""
    groups = {}
    for column in table['columns']:
        ucd = set((column.get('ucd') or '').split(';'))
        axis = 'ra' if 'pos.eq.ra' in ucd else 'dec' if 'pos.eq.dec' in ucd else None
        if axis is None or 'stat.error' in ucd or 'pos.pm' in ucd:
            continue
        context = column.get('reference_context')
        key = digest({'ref': column.get('ref'), 'context': context, 'role': 'main' if 'meta.main' in ucd else 'auxiliary'})
        group = groups.setdefault(key, {'columns': {}, 'reference_context': context,
            'source_ref_label': column.get('ref'), 'role': 'main' if 'meta.main' in ucd else 'auxiliary'})
        group['columns'].setdefault(axis, []).append({'name': column['name'], 'unit': column.get('unit_text'), 'description': column.get('description')})
        attrs = (context or {}).get('attributes', {})
        group.update(frame=attrs.get('system'), equinox=attrs.get('equinox'), reference_epoch=attrs.get('epoch'),
            native_or_service='service_computed' if 'added by cds' in (column.get('description') or '').casefold() else 'source_reported')
    times = [{'column': c['name'], 'unit': c.get('unit_text'), 'description': c.get('description'),
              'reference_context': c.get('reference_context'),
              'observation_role_declared': 'obs' in (c.get('ucd') or '').split(';')}
             for c in table['columns'] if 'time.epoch' in (c.get('ucd') or '').split(';')]
    for group in groups.values():
        group['binding_state'] = ('one_pair_with_declared_reference' if group['reference_context']
            and group['reference_context'].get('state') == 'known'
            and all(len(group['columns'].get(axis, [])) == 1 for axis in ('ra', 'dec')) else 'unresolved_or_multiple_pairs')
    return {'schema_version': 'TableAstrometryContext/1', 'coordinate_groups': list(groups.values()),
            'time_columns': times, 'equinox_used_as_observation_time': False, 'positional_acceptance_granted': False}
