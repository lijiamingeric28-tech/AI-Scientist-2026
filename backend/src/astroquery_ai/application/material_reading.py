"""Small, rebuildable reading profiles projected from sealed facts only."""
from collections import defaultdict
from copy import deepcopy

from astroquery_ai.runtime.codec import canonical


def profile_key(group_id, property_id):
    return f'{group_id}:{property_id or "other"}'


def reading_profiles(body, index=None):
    from .material_workbench import MaterialIndex
    from astroquery_ai.science.results.native_coordinates import table_coordinates
    index = index or MaterialIndex(body)
    contexts = {c.get('context_id'): c for c in body.get('contexts', []) + body.get('resolved_contexts', [])}
    evidence = {e['evidence_id']: e for e in body.get('evidence_index', [])}
    profiles = {}
    for gid, group in index.groups.items():
        for pid in group['properties']:
            ids = index.record_ids(group, pid)
            rows = [index.records[mid] for mid in ids]
            unique = defaultdict(dict)
            for record in rows:
                for field, value in (('units', record.get('unit')), ('representations', record.get('representation'))):
                    if value is not None:
                        unique[field][canonical(value)] = deepcopy(value)
                context = contexts.get((record.get('context_ref') or {}).get('id'), {})
                for condition in context.get('conditions', []):
                    unique['conditions'][canonical(condition)] = deepcopy(condition)
                coordinates = table_coordinates(record, evidence)
                for field in ('epochs', 'bands'):
                    for item in coordinates[field]:
                        unique[field][canonical(item)] = item
            profiles[profile_key(gid, pid)] = {
                'scope': 'material_property', 'material_id': gid, 'property_id': pid,
                'property_name': index.names.get(pid), 'record_count': len(ids),
                'measurement_ids': ids, 'source_count': len({r['source_ref']['id'] for r in rows}),
                'material_record_count': len({mid for part in group['by_property'].values() for mid in part['records']}),
                'figure_count': len(group['by_property'][pid]['figures']),
                'target': deepcopy(body.get('target')),
                **{field: list(unique[field].values()) for field in ('units', 'representations', 'conditions', 'epochs', 'bands')},
                'condition_state': 'recorded' if unique['conditions'] else 'not_recorded',
            }
    return profiles


def profile_for(service, conn, task_id, delivery_id, revision, group_id, pid, **options):
    from .delivery_projections import ProjectionUnavailable
    key = profile_key(group_id, pid)
    try:
        return service.read_projection(conn, task_id, delivery_id, revision,
            lambda reader, scope: reader.get('material_profile', key), **options)
    except ProjectionUnavailable as missing:
        return reading_profiles(missing.body).get(key)
