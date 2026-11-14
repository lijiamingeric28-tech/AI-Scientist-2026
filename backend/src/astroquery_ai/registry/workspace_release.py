"""Local immutable releases: provenance is reused only for exact unchanged scopes."""
from copy import deepcopy
from pathlib import Path

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError
from .workbench_projection import key, ref


def release_ref(release):
    manifest = release['manifest']
    return {'id': manifest['release_id'], 'version': 1, 'content_sha256': manifest['content_sha256']}


def original_release(release):
    while release.get('workspace'):
        release = release['base_release']
    return release


def original_knowledge(knowledge):
    while knowledge.get('base_knowledge'):
        knowledge = knowledge['base_knowledge']
    return knowledge


def active_bundle(repository, conn=None):
    if conn is None:
        with repository.read() as connection:
            return active_bundle(repository, connection)
    settings = {r['key']: (loads(r['payload']), r['revision']) for r in conn.execute(
        "SELECT key,payload,revision FROM settings WHERE key IN ('active_bundle','active_registry','active_knowledge')")}
    registry = settings.get('active_registry', (None, 0))[0]
    knowledge = settings.get('active_knowledge', (None, 0))[0]
    def canonical_ref(value):
        return {'id': value.get('id', value.get('release_id')), 'version': 1, 'content_sha256': value['content_sha256']} if value else None
    registry, knowledge = canonical_ref(registry), canonical_ref(knowledge)
    saved = settings.get('active_bundle', (None, 0))[0]
    if saved and saved['registry_ref'] == registry and saved.get('knowledge_ref') == knowledge:
        return saved
    if not registry:
        raise DomainError('REGISTRY_MISSING', '性质库尚未就绪', 409)
    payload = {'registry_ref': registry, 'knowledge_ref': knowledge}
    return {'id': 'bundle_' + digest(payload), 'revision': max(v[1] for v in settings.values()), **payload}


def load_workspace_release(service, directory, manifest):
    if content_hash(manifest) != manifest.get('content_sha256'):
        raise DomainError('MANIFEST_HASH', '本地发布清单哈希不匹配', 422)
    workspace_file = service._file(directory, 'workspace.json')
    stat = workspace_file.stat()
    signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    cache = service.__dict__.setdefault('_workspace_cache', {})
    cached = cache.get(str(directory))
    if cached and cached[0] == manifest and cached[1] == signature:
        base = service.load(cached[2]['workspace']['base_registry_ref']['id'])
        if base is cached[2]['base_release']:
            return cached[2]
    payload = loads(workspace_file.read_bytes())
    if digest(payload) != manifest['workspace_sha256']:
        raise DomainError('RELEASE_FILE_HASH', '本地发布内容哈希不匹配', 422)
    base = service.load(payload['base_registry_ref']['id'])
    if release_ref(base) != payload['base_registry_ref']:
        raise DomainError('WORKSPACE_BASE_CHANGED', '本地发布的基础版本不匹配', 422)
    if payload.get('execution_manifest'):
        from .user_execution import compile_execution
        expected, _, errors = compile_execution(payload['projection'], base)
        if errors or payload['execution_manifest'] != expected:
            raise DomainError('USER_EXECUTION_MANIFEST_INVALID', 'User execution manifest cannot be reproduced', 422)
    # Exact original objects remain available for source validation and audit.
    result = {**base, 'manifest': manifest, 'base_release': base, 'workspace': payload}
    if payload.get('execution_manifest'):
        from .user_execution import local_conversion_policy
        policy = local_conversion_policy()
        result['data'] = {**base['data'], 'conversion-policies': [p for p in base['data']['conversion-policies'] if p['policy_id'] != policy['policy_id']] + [policy]}
        result['objects'] = {**base['objects'], policy['policy_id']: policy}
    from .amendments import reference_key
    from .models import PropertyDefinition, OutputProfile
    result['definition_views'] = dict(base.get('definition_views', {}))
    result['profile_views'] = dict(base.get('profile_views', {}))
    result['definitions'] = dict(base['definitions']); result['profiles'] = dict(base['profiles'])
    from .user_execution import UserPropertyDefinition, UserOutputProfile
    for prop in payload['projection']['properties'].values():
        user = any(e['contract']['property_key'] == prop['id'] for e in payload.get('execution_manifest', {}).get('contracts', {}).values())
        if prop.get('automatic_conversion_ready') or user:
            definition = (UserPropertyDefinition if user else PropertyDefinition).model_validate(prop['definition'])
            result['definition_views'][reference_key(prop['definition_ref'])] = definition
            result['definitions'][definition.property_id] = definition
            output_profiles = list(prop['output_profiles'])
            output_profiles.extend(b['output_profile'] for b in payload['projection']['bindings'].values() if b['property_key'] == prop['id'] and b.get('output_profile'))
            for p in output_profiles:
                profile = (UserOutputProfile if user else OutputProfile).model_validate(p)
                result['profile_views'][reference_key(ref(p, 'profile'))] = profile
                result['profiles'][profile.profile_id] = profile
    if len(cache) >= 4:
        cache.pop(next(iter(cache)))
    cache[str(directory)] = (manifest, signature, result)
    return result


def workspace_support(release, otypes, subject_class_id, *, user_type_ref=None):
    from .service import RegistryService
    from .compiler import matches
    base = original_release(release); projection = release['workspace']['projection']
    result = deepcopy(RegistryService.support(base, otypes, subject_class_id))
    exclusions = base.get('candidate', {}).get('data', {}).get('unapproved_aggregate_composition_and_rules', {}).get('exclusions', base.get('compiled', {}).get('exclusions', []))
    if any(g.get('reason') == 'excluded_composition' for g in result.get('gaps', [])) or any(matches(c.get('when', c.get('condition', c)), set(otypes), subject_class_id) for c in exclusions):
        result['bindings'] = []
        if not any(g.get('reason') == 'excluded_composition' for g in result.get('gaps', [])):
            result['gaps'].append({'reason': 'excluded_composition'})
        result['support_hash'] = digest({k: v for k, v in result.items() if k != 'support_hash'})
        return result
    selected_types = set(otypes)
    if user_type_ref:
        identifier = user_type_ref.get('id') if isinstance(user_type_ref, dict) else user_type_ref
        selected = projection['types'].get(identifier)
        if not selected or selected['status'] != 'active' or selected['id'] == selected.get('standard_otype') or selected['standard_otype'] not in otypes:
            raise DomainError('USER_TYPE_INCOMPATIBLE', '自定义子类型不兼容当前已确认的SIMBAD类型', 422)
        if isinstance(user_type_ref, dict) and (user_type_ref.get('version') != selected['revision'] or user_type_ref.get('content_sha256') != type_hash(selected)):
            raise DomainError('USER_TYPE_STALE', '自定义类型版本不匹配', 409)
        cursor = selected
        visited = set()
        while cursor and cursor['id'] != cursor.get('standard_otype'):
            if cursor['id'] in visited or cursor['status'] != 'active':
                raise DomainError('USER_TYPE_INCOMPATIBLE', '自定义类型父链不可用', 422)
            visited.add(cursor['id'])
            if (not all(matches(c, set(otypes), subject_class_id) for c in cursor.get('conditions', []))
                    or any(matches(c, set(otypes), subject_class_id) for c in cursor.get('excluded_conditions', []))):
                raise DomainError('USER_TYPE_CONDITIONS', '当前确认类型不满足自定义类型父链条件', 422)
            selected_types.add(cursor['id']); cursor = projection['types'].get(cursor['parent_id'])
        if not cursor or cursor['status'] != 'active' or cursor['id'] != selected['standard_otype']:
            raise DomainError('USER_TYPE_INCOMPATIBLE', '自定义类型父链锚点不一致', 422)
        if (not all(matches(c, set(otypes), subject_class_id) for c in cursor.get('conditions', []))
                or any(matches(c, set(otypes), subject_class_id) for c in cursor.get('excluded_conditions', []))):
            raise DomainError('USER_TYPE_CONDITIONS', '当前确认类型不满足官方锚点的本地限制', 422)
    eligible = []
    for binding in projection['bindings'].values():
        prop = projection['properties'].get(binding['property_key']); target = projection['types'].get(binding['type_id'])
        if not prop or not target or binding['status'] != 'active' or prop['status'] != 'active' or target['status'] != 'active' or binding['type_id'] not in selected_types:
            continue
        if (not all(matches(c, set(otypes), subject_class_id) for c in target.get('conditions', []))
                or any(matches(c, set(otypes), subject_class_id) for c in target.get('excluded_conditions', []))):
            continue
        if prop['definition']['subject_class_id'] != subject_class_id:
            continue
        if binding['conditions'] and not any(matches(c, selected_types, subject_class_id) for c in binding['conditions']):
            continue
        exclusions = binding.get('excluded_conditions', [])
        if any(matches(c.get('when', c.get('condition', c)), selected_types, subject_class_id) for c in exclusions):
            continue
        eligible.append((binding, prop))
    retained = []
    for source in result['bindings']:
        exact = [(b, p) for b, p in eligible if p['definition_ref'] == ref(source['definition']) and b['profile_ref'] == ref(source['output_profile'], 'profile') and b.get('automatic_execution_ready', True)]
        if exact:
            retained.append(source)
    for binding, prop in eligible:
        from .user_execution import execution_binding
        declared = execution_binding(release, binding, prop)
        if declared:
            retained.append(declared)
            continue
        if not any(prop['definition_ref'] == ref(b['definition']) and binding['profile_ref'] == ref(b['output_profile'], 'profile') for b in retained):
            result['gaps'].append({'property_id': prop['property_id'], 'property_key': prop['id'],
                'binding_id': binding['id'], 'reason': 'workspace_scope_not_scientifically_qualified',
                'automatic_execution_ready': False, 'source_data_retained': True})
    result['bindings'] = retained
    result['user_type_ref'] = user_type_ref
    result['support_hash'] = digest({k: v for k, v in result.items() if k != 'support_hash'})
    return result


def qualification_base_ref(release, bindings):
    if not release.get('workspace'):
        return release_ref(release)
    projection = release['workspace']['projection']
    for frozen in bindings:
        if not any(p['status'] == 'active' and p.get('definition_unchanged', True) and p['definition_ref'] == ref(frozen['definition'])
                   and any(ref(profile, 'profile') == ref(frozen['output_profile'], 'profile') for profile in p['output_profiles'])
                   for p in projection['properties'].values()):
            return None
        source_bindings = [b.get('source_binding', {}) for b in projection['bindings'].values()
            if b['status'] == 'active' and b.get('automatic_execution_ready', True)]
        exact = [s for s in source_bindings if s.get('definition') == frozen['definition'] and s.get('output_profile') == frozen['output_profile']]
        allowed_rules = {key(r) for s in exact for r in s.get('rule_refs', [])}
        allowed_dependencies = {key(r) for s in exact for r in s.get('dependency_refs', [])}
        if (not exact or any(key(r) not in allowed_rules for r in frozen.get('rule_refs', []))
                or any(key(r) not in allowed_dependencies for r in frozen.get('dependency_refs', []))):
            return None
    return release_ref(original_release(release))


def knowledge_compatibility(knowledge, projection, *, original_source=True):
    compatible, gaps, links = [], [], {}
    if not knowledge:
        return {'compatible_binding_ids': [], 'gaps': [], 'links': {}, 'available': 0, 'missing': len(projection['properties'])}
    if original_source:
        knowledge = original_knowledge(knowledge)
    exact_index = {}
    for binding in projection['bindings'].values():
        prop = projection['properties'][binding['property_key']]
        receipt = binding.get('source_binding', {}).get('candidate_projection_receipt', {})
        drefs = [prop['definition_ref'], *prop.get('source_refs', [])]
        prefs = [binding['profile_ref'], receipt.get('source_profile_ref', {})]
        for dref in {key(r) for r in drefs if r}:
            for pref in {key(r) for r in prefs if r}:
                exact_index.setdefault((dref, pref), []).append((binding, prop))
    for source in knowledge.get('data', {}).get('bindings', []):
        identifier = binding_identifier(source)
        dref = source.get('definition_ref', {}); pref = source.get('output_profile_ref', source.get('profile_ref', {}))
        candidates = exact_index.get((key(dref), key(pref)), []) if dref and pref else []
        if source.get('otype'):
            candidates = [(b, p) for b, p in candidates if b['type_id'] == source['otype']]
        valid = [(b, p) for b, p in candidates if b['status'] == p['status'] == projection['types'][b['type_id']]['status'] == 'active'
                 and p.get('definition_unchanged', True) and b.get('automatic_execution_ready', True)]
        reason = None if valid else 'exact_definition_profile_or_applicability_changed'
        if valid:
            compatible.append(identifier)
        else:
            gaps.append({'binding_id': identifier, 'entry_ids': source.get('entry_ids', [source.get('entry_id') or source.get('entry_ref', {}).get('id')]), 'reason': reason})
        entry_ids = source.get('entry_ids', [source.get('entry_id') or source.get('entry_ref', {}).get('id')])
        if source.get('status') == 'missing' or not any(e in knowledge.get('entries', {}) for e in entry_ids):
            gaps.append({'binding_id': identifier, 'entry_ids': entry_ids, 'reason': source.get('reason') or 'author_knowledge_coverage_missing', 'coverage_missing': True})
        for b, p in candidates:
            for entry_id in source.get('entry_ids', [source.get('entry_id') or source.get('entry_ref', {}).get('id')]):
                if not entry_id or entry_id not in knowledge.get('entries', {}) or source.get('status') == 'missing':
                    continue
                entry = knowledge.get('entries', {}).get(entry_id, {})
                link = {'entry_id': entry_id, 'title': entry.get('title', entry.get('name', entry_id)),
                    'compatibility': 'compatible' if valid else 'suspended', 'reason': reason}
                if link not in links.setdefault(p['id'], []):
                    links[p['id']].append(link)
    return {'compatible_binding_ids': sorted(compatible), 'gaps': gaps, 'links': links,
            'available': sum(any(l['compatibility'] == 'compatible' for l in links.get(p, [])) for p in projection['properties']),
            'missing': sum(not any(l['compatibility'] == 'compatible' for l in links.get(p, [])) for p in projection['properties'])}


def load_workspace_knowledge(service, directory, manifest):
    if content_hash(manifest) != manifest.get('content_sha256'):
        raise DomainError('KB_MANIFEST_HASH', '本地知识发布清单哈希不匹配', 422)
    path = (Path(directory) / 'compatibility.json')
    payload = loads(path.read_bytes())
    if digest(payload) != manifest['compatibility_sha256']:
        raise DomainError('KB_RELEASE_HASH', '知识兼容性内容不可核验', 422)
    base = service.load(payload['base_knowledge_ref'])
    if release_ref(base) != payload['base_knowledge_ref']:
        raise DomainError('KB_BASE_CHANGED', '原知识发布版本不匹配', 422)
    registry = service.registry.load(manifest['registry_release_ref']['id'])
    if release_ref(registry) != manifest['registry_release_ref']:
        raise DomainError('KB_REGISTRY_BINDING', '本地知识与性质发布不匹配', 422)
    cumulative = payload.get('compatibility_policy') == 'cumulative-exact-source/2'
    expected = knowledge_compatibility(base, registry['workspace']['projection'], original_source=cumulative)
    if payload['compatible_binding_ids'] != expected['compatible_binding_ids'] or payload['gaps'] != expected['gaps']:
        raise DomainError('KB_COMPATIBILITY_CHANGED', '知识兼容映射不能由原文和精确引用重现', 422)
    allowed = set(payload['compatible_binding_ids'])
    source = original_knowledge(base) if cumulative else base
    result = deepcopy(source)
    result['manifest'] = manifest; result['base_knowledge'] = base; result['workspace'] = payload
    result['data']['bindings'] = [b for b in source['data']['bindings'] if binding_identifier(b) in allowed]
    result['gaps'] = payload['gaps']
    if result.get('author'):
        result['author']['bindings'] = deepcopy(result['data']['bindings'])
    return result


def type_hash(item):
    return digest({k: item.get(k) for k in ('id', 'revision', 'label', 'description', 'aliases', 'parent_id', 'standard_otype', 'status', 'conditions', 'excluded_conditions')})


def user_type_choices(release, verified_otypes):
    types = release.get('workspace', {}).get('projection', {}).get('types', {})
    choices = []
    for item in types.values():
        if item['id'] == item.get('standard_otype') or item['status'] != 'active' or item['standard_otype'] not in verified_otypes:
            continue
        cursor = item; seen = set()
        while cursor and cursor['id'] != cursor.get('standard_otype'):
            if cursor['id'] in seen or cursor['status'] != 'active':
                cursor = None; break
            seen.add(cursor['id']); cursor = types.get(cursor.get('parent_id'))
        if not cursor or cursor['status'] != 'active' or cursor['id'] != item['standard_otype']:
            continue
        choices.append({**deepcopy(item), 'content_sha256': type_hash(item)})
    return sorted(choices, key=lambda item: (item['label'], item['id']))


def binding_identifier(binding):
    return binding.get('binding_id') or binding.get('item_id') or binding.get('mapping_id') or digest(binding)
