"""Exact immutable registry projections shared by every workbench read surface."""
from copy import deepcopy

from astroquery_ai.runtime.codec import digest


def ref(value, kind='definition'):
    return {'id': value['property_id' if kind == 'definition' else 'profile_id'],
            'version': value['definition_version' if kind == 'definition' else 'version'],
            'content_sha256': value['content_sha256']}


def key(reference):
    return digest({'id': reference['id'], 'version': str(reference['version']), 'content_sha256': reference['content_sha256']})


def plain(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else deepcopy(value)


def source_projection(registry):
    if registry.get('workspace'):
        return deepcopy(registry['workspace']['projection'])
    data = registry['data']
    candidate = registry.get('candidate', {}).get('data', {})
    types, properties, bindings = {}, {}, {}
    taxonomy = data.get('taxonomy', candidate.get('taxonomy', {}))
    nodes = taxonomy.get('nodes', []) if isinstance(taxonomy, dict) else taxonomy
    node_index = {n.get('otype', n.get('code')): n for n in nodes}
    for item in data.get('type-profiles', []):
        code = item['otype']; node = node_index.get(code, {})
        types[code] = {'id': code, 'kind': 'type', 'code': code,
            'label': node.get('label_cn') or node.get('name_cn') or node.get('label') or item.get('name_cn') or code,
            'description': node.get('description', item.get('description', '')), 'aliases': node.get('aliases', []),
            'parent_id': node.get('parent_otype') or node.get('parent_id'), 'standard_otype': code,
            'origin': 'builtin', 'status': 'active', 'revision': 1, 'property_count': 0,
            'conditions': [], 'source_refs': item.get('source_refs', [])}
    definitions = registry.get('definition_views', registry['definitions'])
    profiles = [plain(p) for p in registry.get('profile_views', registry['profiles']).values()]
    for model in definitions.values():
        definition = plain(model); reference = ref(definition); record_key = 'property_' + key(reference)
        properties[record_key] = {'id': record_key, 'kind': 'property', 'property_id': definition['property_id'],
            'label': definition['name_cn'], 'description': definition['description'], 'aliases': definition['aliases'],
            'family_id': definition['family_id'], 'origin': 'builtin', 'status': 'active', 'revision': 1,
            'definition_ref': reference, 'definition': definition,
            'source_quantity_identity': {'property_id': definition['property_id'], 'quantity_key': definition['quantity_key']},
            'source_refs': deepcopy(registry.get('source_definition_refs', {}).get(__import__('astroquery_ai.registry.amendments', fromlist=['reference_key']).reference_key(reference), [reference])),
            'output_profiles': [], 'automatic_conversion_ready': True}
    rules = {r['rule_id']: r for r in candidate.get('unapproved_aggregate_composition_and_rules', {}).get('rules', [])}
    if not rules:
        rules = {r['rule_id']: r for r in registry.get('compiled', {}).get('rules', [])}
    exclusions = candidate.get('unapproved_aggregate_composition_and_rules', {}).get('exclusions', registry.get('compiled', {}).get('exclusions', []))
    from .service import RegistryService
    from .consumer import potential_type_bindings
    for code in types:
        if registry.get('candidate'):
            choices = potential_type_bindings(registry, code)
        else:
            subjects = {d.subject_class_id for d in registry['definitions'].values()}
            choices = [b for subject in subjects for b in RegistryService.support(registry, [code], subject)['bindings']]
        for source in choices:
            definition, profile = source['definition'], source['output_profile']
            property_key = 'property_' + key(ref(definition))
            if property_key not in properties:
                continue
            prop = properties[property_key]
            if ref(profile, 'profile') not in [ref(p, 'profile') for p in prop['output_profiles']]:
                prop['output_profiles'].append(deepcopy(profile))
            identity = {'type_id': code, 'property_key': property_key, 'profile_ref': ref(profile, 'profile')}
            binding_id = 'binding_' + digest(identity)
            source_rules = [rules[r['id']] for r in source.get('rule_refs', []) if r['id'] in rules]
            conditions = [r.get('when', r.get('condition')) for r in source_rules if r.get('when', r.get('condition'))]
            contexts = source.get('applicability_type_contexts', [[code]])
            bindings[binding_id] = {**identity, 'id': binding_id, 'definition_ref': ref(definition),
                'conditions': deepcopy(conditions), 'excluded_conditions': deepcopy(exclusions),
                'display_order': min((r.get('display_order', 0) for r in source_rules), default=0),
                'status': 'active', 'conditional': not any(set(c) <= {code} for c in contexts),
                'origin': 'builtin', 'revision': 1, 'rule_refs': deepcopy(source.get('rule_refs', [])),
                'source_binding': deepcopy(source)}
    for prop in properties.values():
        if not prop['output_profiles']:
            prop['output_profiles'] = [p for p in profiles if p['property_id'] == prop['property_id'] and p['definition_version'] == prop['definition']['definition_version']]
    return decorate({'types': types, 'properties': properties, 'bindings': bindings})


def decorate(projection):
    for t in projection['types'].values():
        t['property_count'] = len({b['property_key'] for b in projection['bindings'].values() if b['type_id'] == t['id'] and b['status'] == 'active' and projection['properties'].get(b['property_key'], {}).get('status') == 'active'})
    for prop in projection['properties'].values():
        prop['type_count'] = len({b['type_id'] for b in projection['bindings'].values() if b['property_key'] == prop['id'] and b['status'] == 'active' and projection['types'].get(b['type_id'], {}).get('status') == 'active'})
        profile = next(iter(prop['output_profiles']), {})
        prop['unit_label'] = profile.get('unit', {}).get('canonical_symbol') or profile.get('unit', {}).get('kind', '')
        prop['representation_label'] = profile.get('representation', {}).get('kind', '')
        prop['subject_label'] = prop['definition']['subject_class_id']
        prop.setdefault('knowledge_coverage', {'available': 0, 'missing': 1})
    return projection


def apply_operations(base, operations):
    result = deepcopy(base)
    for operation in operations:
        collection = result[operation['kind']]
        if operation['action'] == 'remove':
            collection.pop(operation['id'], None)
        else:
            collection[operation['id']] = deepcopy(operation['item'])
    return decorate(result)
