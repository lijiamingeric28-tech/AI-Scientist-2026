"""One immutable registry/knowledge context per query, independent of defaults."""
from copy import deepcopy

from astroquery_ai.runtime.errors import DomainError


def pin_bundle(app, draft, conn=None, *, refresh=False):
    if draft.get('registry_bundle') and not refresh:
        return
    # Legacy drafts already fixed to a release must not silently upgrade.
    if draft.get('registry_release') and not refresh:
        return
    try:
        bundle = app.registry.active_bundle(conn)
    except DomainError as exc:
        if exc.code != 'REGISTRY_MISSING':
            raise
        return  # Initial installation may still be pending; prepare pins once.
    draft['registry_bundle'] = deepcopy(bundle)
    draft['registry_release'] = deepcopy(bundle['registry_ref'])
    if refresh:
        draft.update(user_type_ref=None, property_support=None, selected_property_ids=[],
                     model_property_selection=None, issues=[])


def verified_types(target):
    if not target:
        return []
    types = {target['primary_otype']} if '?' not in target['primary_otype'] else set()
    for assertion in target.get('classification_assertions', []):
        subject = assertion.get('subject_identity_ref')
        subject = subject.get('id') if isinstance(subject, dict) else subject
        if (assertion.get('state') == 'current_verified' and subject == target['target_id']
                and assertion.get('evidence_refs') and assertion.get('canonical_otype')):
            types.add(assertion['canonical_otype'])
    return sorted(types)


def pinned_knowledge(app, draft):
    bundle = draft.get('registry_bundle')
    reference = bundle.get('knowledge_ref') if bundle else None
    if bundle and not reference:
        raise DomainError('INSIGHT_KB_PIN_MISSING', '本任务固定版本中没有洞察知识发布', 409)
    knowledge = app.knowledge.load(reference) if reference else app.knowledge.load()
    manifest = knowledge['manifest']
    if reference:
        exact = {'id': manifest['release_id'], 'version': 1, 'content_sha256': manifest['content_sha256']}
        if exact != reference or manifest.get('registry_release_ref') != bundle['registry_ref']:
            raise DomainError('REGISTRY_BUNDLE_MISMATCH', '规范与洞察知识版本组合不一致', 409)
    elif draft.get('registry_release') and manifest.get('registry_release_ref') != draft['registry_release']:
        raise DomainError('REGISTRY_BUNDLE_MISMATCH', '旧草稿的规范与当前洞察知识版本组合不一致，请显式升级规范并重新确认', 409)
    return knowledge


def subtype_choices(release, target):
    if not release.get('workspace') or not target:
        return []
    from astroquery_ai.registry.workspace_release import user_type_choices
    return user_type_choices(release, verified_types(target))


def applicability_subjects(release, otypes, user_type_ref=None):
    """Include local applicability contexts even when the base has no binding."""
    subjects = {context[1] for context in release.get('context_bindings', {}) if context[0] in otypes}
    projection = release.get('workspace', {}).get('projection')
    if not projection:
        return subjects
    selected = set(otypes)
    cursor = projection['types'].get((user_type_ref or {}).get('id'))
    while cursor and cursor['id'] not in selected:
        selected.add(cursor['id'])
        cursor = projection['types'].get(cursor.get('parent_id'))
    for binding in projection['bindings'].values():
        prop = projection['properties'].get(binding['property_key'])
        target = projection['types'].get(binding['type_id'])
        if (binding['type_id'] in selected and binding['status'] == 'active' and prop and target
                and prop['status'] == target['status'] == 'active'):
            subjects.add(prop['definition']['subject_class_id'])
    return subjects


def qualification_reference(app, spec):
    """No authority is created: compare frozen dependencies to original source."""
    from astroquery_ai.registry.workspace_release import qualification_base_ref, release_ref
    reference = spec.get('registry_release') or {}
    if not all(reference.get(k) for k in ('id', 'version', 'content_sha256')):
        return None
    try:
        release = app.registry.load(reference['id'])
        if not release.get('manifest') or release_ref(release) != reference:
            return None
        bindings = spec['properties']
        if any(b.get('user_execution_ref') for b in bindings):
            from astroquery_ai.registry.user_execution import verified_user_bindings
            declared = verified_user_bindings(app, spec)
            bindings = [b for b in bindings if not (b.get('user_execution_ref') and b.get('property_id') in declared)]
        return qualification_base_ref(release, bindings)
    except DomainError:
        return None


def apply_local_labels(release, support):
    """Local reading/search labels carry no scientific definition authority."""
    projection = release.get('workspace', {}).get('projection')
    if not projection:
        return
    from astroquery_ai.registry.workbench_projection import key, ref
    properties = {key(p['definition_ref']): p for p in projection['properties'].values()}
    for binding in support['bindings']:
        item = properties.get(key(ref(binding['definition'])))
        if item:
            binding['display_name'] = item.get('label')
            binding['display_aliases'] = deepcopy(item.get('aliases', []))
    for gap in support.get('gaps', []):
        item = projection['properties'].get(gap.get('property_key'))
        if item:
            gap['label'] = item['label']
    from astroquery_ai.runtime.codec import digest
    support['support_hash'] = digest({k: v for k, v in support.items() if k != 'support_hash'})
