"""Exact property bindings and bounded workbench graph projections.

The aliases below describe curated connectors, not a replacement registry of
scientific definitions. Unknown literal bindings remain visibly unreviewed.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256


PROPERTY_BINDINGS = [
    ('luminosity', 'prop_luminosity', '光度 (Luminosity)', ['光度']),
    ('effective_temperature', 'prop_teff', '有效温度 (Teff)', ['Effective Temperature', '有效温度', 'teff']),
    ('mass', 'prop_mass', '天体质量 (Mass)', ['质量']),
    ('radius', 'prop_radius', '天体半径 (Radius)', ['半径']),
    ('distance', 'prop_distance', '天体距离 (Distance)', ['距离']),
    ('extinction', 'prop_extinction', '星际消光 (Extinction)', ['消光']),
    ('reddening', 'prop_reddening', '色余红化 (Reddening)', ['红化']),
    ('parallax', 'prop_parallax', '天体测量视差 (Parallax)', ['视差', 'plx']),
    ('orbital_period', 'prop_period', '轨道周期 (Period)', ['Orbital Period', '轨道周期']),
    ('metallicity', 'prop_metallicity', '金属丰度 (Metallicity)', ['金属丰度']),
    ('surface_gravity', 'prop_surface_gravity', '表面重力 (Surface Gravity)', ['Surface Gravity', '表面重力']),
    ('density', 'prop_density', '物质密度 (Density)', ['密度']),
    ('dispersion_measure', 'prop_dispersion', '色散量 (Dispersion Measure)', ['Dispersion Measure', '色散量', 'dm']),
    ('radial_velocity', 'prop_radial_velocity', '视向速度 (Radial Velocity)', ['Radial Velocity', '视向速度', 'rv']),
]
_ALIASES = {}
_PROPERTIES = {}
for _pid, _node_id, _label, _aliases in PROPERTY_BINDINGS:
    _PROPERTIES[_pid] = {'id': _pid, 'label': _label, 'node_id': _node_id, 'binding_state': 'curated',
                         'provenance': 'curated_property_aliases'}
    for _alias in (_pid, _node_id, *_aliases):
        _ALIASES[_alias.casefold()] = _pid


def property_key(value):
    literal = str(value).strip()
    return _ALIASES.get(literal.casefold(), literal.casefold())


def property_info(value):
    key = property_key(value)
    return deepcopy(_PROPERTIES.get(key, {'id': key, 'label': str(value).strip(),
        'node_id': 'property:' + key, 'binding_state': 'unreviewed', 'provenance': 'entry.properties'}))


def entry_properties(entry):
    return {property_key(value): property_info(value) for value in entry.get('properties', []) if str(value).strip()}


def entry_source(entry):
    return 'override' if entry.get('is_override') else 'user' if entry.get('is_user') else 'builtin'


def entry_summary(entry):
    result = deepcopy(entry)
    description = str(result.get('description') or '')
    result['description'] = description[:300]
    result['description_preview'] = description[:300]
    result['description_truncated'] = len(description) > 300
    result['source'] = entry_source(entry)
    return result


def category_facets(entries, categories):
    counts = Counter(entry.get('category', 'user_private') for entry in entries)
    result = [{**deepcopy(category), 'count': counts.pop(category['id'], 0)} for category in categories]
    result.extend({'id': key, 'label': key, 'color': '#0ea5e9', 'count': count, 'is_custom': True}
                  for key, count in sorted(counts.items()))
    return result


def _edge(source, target, relation_type, label, provenance):
    identity = sha256(f'{source}\0{target}\0{relation_type}'.encode()).hexdigest()[:20]
    return {'id': 'edge:' + identity, 'source': source, 'target': target,
            'label': label, 'relation_type': relation_type, 'provenance': provenance}


def graph_projection(entries, categories, *, total_entries, revision, view, focus_id=None, limit=80, legacy=False):
    """Project only the filtered corpus. The budget includes every node kind."""
    budget = min(200, max(1, limit))
    facets = category_facets(entries, categories)
    nodes, edges = [], []
    matched = len(entries)
    filtered = matched
    shown = 0
    represented = 0
    if view == 'overview':
        active = [category for category in facets if category['count']]
        # If custom categories exceed the budget, the final real aggregate keeps
        # coverage truthful and keyword search still reaches every entry.
        visible = active if len(active) <= budget else active[:max(0, budget - 1)]
        for category in visible:
            nodes.append({'id': 'category:' + category['id'], 'kind': 'category',
                'label': category['label'], 'category': category['id'], 'is_property': False,
                'count': category['count'], 'color': category['color'], 'order': category.get('order', 0)})
            represented += category['count']
        if len(visible) < len(active):
            nodes.append({'id': 'aggregate:categories', 'kind': 'aggregate', 'label': '其他分类',
                          'category': None, 'is_property': False, 'count': matched - represented})
            represented = matched
        # Aggregate only explicit property bindings. Counts describe supporting
        # entries, never inferred scientific equivalence or free-text matches.
        by_category_property = Counter()
        properties, property_counts = {}, Counter()
        for entry in entries:
            own = entry_properties(entry)
            properties.update(own)
            property_counts.update(own.keys())
            by_category_property.update((entry.get('category', 'user_private'), key) for key in own)
        category_nodes = {node['category']: node['id'] for node in nodes if node['kind'] == 'category'}
        for key in sorted(properties, key=lambda key: (-property_counts[key], key))[:budget - len(nodes)]:
            info = properties[key]
            nodes.append({'id': info['node_id'], 'kind': 'property', 'property_id': key,
                          'label': info['label'], 'category': 'concepts_and_catalogs', 'is_property': True,
                          'count': property_counts[key], 'binding_state': info['binding_state'],
                          'provenance': info['provenance']})
            for category in active:
                count = by_category_property[(category['id'], key)]
                if not count or category['id'] not in category_nodes:
                    continue
                relation = _edge(category_nodes[category['id']], info['node_id'], 'category_property',
                    '关联性质', {'source': 'entry.properties', 'aggregation': 'entry_count',
                               'binding_state': info['binding_state'], 'property_id': key})
                relation['count'] = count
                edges.append(relation)
    else:
        candidates = entries
        focus = next((entry for entry in entries if entry['id'] == focus_id), None)
        if view == 'focus':
            if focus is None:
                candidates = []
            else:
                own = set(entry_properties(focus))
                # One hop through explicit properties, derivation, or user links.
                candidates = [focus] + [entry for entry in entries if entry['id'] != focus['id'] and (
                    own.intersection(entry_properties(entry)) or entry.get('base_id') == focus['id']
                    or focus.get('base_id') == entry['id'] or entry['id'] in focus.get('related_ids', [])
                    or focus['id'] in entry.get('related_ids', []))]
            matched = len(candidates)
        property_counts = Counter(key for entry in candidates for key in entry_properties(entry))
        # Reserve modest space for connectors without dropping an isolated focus.
        prop_budget = min(len(property_counts), 14, max(0, budget // 3))
        selected = candidates[:min(120, budget - 14) if legacy else max(1, budget - prop_budget)]
        selected_ids = {entry['id'] for entry in selected}
        selected_props = {}
        for entry in selected:
            node = entry_summary(entry)
            node.update(kind='entry', label=entry.get('title', entry['id']), is_property=False)
            nodes.append(node)
            selected_props.update(entry_properties(entry))
        if legacy:
            # Legacy clients expect the fourteen standard connector nodes even
            # when a connector has no supported edge in this filtered slice.
            selected_props.update({key: deepcopy(info) for key, info in _PROPERTIES.items()})
        for key in sorted(selected_props, key=lambda key: (
                0 if legacy and key in _PROPERTIES else 1, -property_counts[key], key))[:budget - len(nodes)]:
            info = selected_props[key]
            nodes.append({'id': info['node_id'], 'kind': 'property', 'property_id': key,
                          'label': info['label'], 'category': 'concepts_and_catalogs',
                          'is_property': True, 'count': property_counts[key],
                          'binding_state': info['binding_state'], 'provenance': info['provenance']})
            for entry in selected:
                if key in entry_properties(entry):
                    edges.append(_edge(entry['id'], info['node_id'], 'property', '关联性质',
                        {'source': 'entry.properties', 'binding_state': info['binding_state'], 'property_id': key}))
        for entry in selected:
            parent = entry.get('base_id')
            if parent in selected_ids and parent != entry['id']:
                edges.append(_edge(entry['id'], parent, 'derived_from', '派生自基准理论', 'entry.base_id'))
            for target in dict.fromkeys(entry.get('related_ids', [])):
                if target in selected_ids and target != entry['id']:
                    edges.append(_edge(entry['id'], target, 'user_link', '用户关联', 'entry.related_ids'))
        shown = len(selected)
        represented = shown
    return {'nodes': nodes, 'edges': edges, 'categories': facets, 'meta': {
        'total_entries': total_entries, 'filtered_entries': filtered,
        'matched_entries': matched, 'shown_entries': shown,
        'represented_entries': represented, 'node_count': len(nodes),
        'truncated': represented < matched, 'view': view, 'revision': revision}}
