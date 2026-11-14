"""User-declared execution, separate from source scientific review authority."""
from copy import deepcopy
from decimal import Decimal

from pydantic import Field

from astroquery_ai.runtime.codec import content_hash, decimal_literal, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import Ref
from .models import Explanation, OutputProfile, PropertyDefinition, Representation
from .workbench_projection import key, ref

PROTOCOL = 'user-property-execution/1'


def local_conversion_policy():
    policy = {'policy_id': 'user-declared-same-quantity', 'version': 1, 'user_declared': True,
        'name_cn': '用户声明：同一科学量的现有转换',
        'description': '用户发布定义与转换样例后，使用现有单位和表示转换引擎；不授予科学审定，不推导其他科学量。',
        'allowed_operators': ['linear', 'log10', 'ln', 'magnitude', 'text', 'category', 'boolean', 'relation'],
        'quantity_scope': 'exact_user_declared_quantity_key', 'software_protocol': PROTOCOL}
    policy['content_sha256'] = content_hash(policy)
    return policy


class UserPropertyDefinition(PropertyDefinition):
    evidence_refs: list[Ref] = Field(default_factory=list)
    review_ref: Ref | None = None
    explanation: Explanation | None = None


class UserOutputProfile(OutputProfile):
    review_ref: Ref | None = None


def bounded_decimal(value):
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError('Decimal input exceeds 128-character bound')
    number = Decimal(decimal_literal(value))
    if abs(number.as_tuple().exponent) > 1000 or abs(number.adjusted()) > 1000:
        raise ValueError('Decimal exponent exceeds supported bound')
    return number


def compile_execution(projection, release):
    """Recompute examples and exact contracts; never accept client readiness flags."""
    from astroquery_ai.science.normalization import MATH_POLICY, SameQuantityTransform
    from astroquery_ai.science.conversion_policy import conversion_permission
    from astroquery_ai.science.unit_declarations import output_coordinate_unit
    contracts, capabilities, errors = {}, {}, []
    by_property = {}
    for binding in projection['bindings'].values():
        by_property.setdefault(binding['property_key'], []).append(binding)
    local_policy = local_conversion_policy()
    policies = {key({'id': p['policy_id'], 'version': p['version'], 'content_sha256': p['content_sha256']}): p
                for p in [*release['data']['conversion-policies'], local_policy]}
    for prop in projection['properties'].values():
        unchanged = prop.get('automatic_conversion_ready') and prop.get('definition_unchanged', True)
        local_bindings = [b for b in by_property.get(prop['id'], []) if b['status'] == 'active' and not b.get('automatic_execution_ready', True)]
        builtin = unchanged and not local_bindings
        origin = 'builtin' if builtin else 'user_defined' if prop['origin'] == 'user' else 'user_modified'
        profiles = list(prop['output_profiles'])
        for binding in by_property.get(prop['id'], []):
            if binding['status'] == 'active' and binding.get('output_profile') and binding['output_profile'] not in profiles:
                profiles.append(binding['output_profile'])
        reports, checked_profiles = [], set()
        valid = prop['status'] == 'active'
        try:
            UserPropertyDefinition.model_validate(prop['definition'])
            for profile in profiles:
                UserOutputProfile.model_validate(profile)
        except ValueError:
            valid = False
            if prop['status'] == 'active':
                errors.append({'code': 'USER_EXECUTION_DEFINITION_INVALID', 'id': prop['id'], 'message': '定义或输出配置未通过结构校验'})
        for index, example in enumerate(prop.get('execution_examples', []) if prop['status'] == 'active' else []):
            report = {'label': example.get('label', str(index + 1)), 'state': 'passed'}
            try:
                reference = example.get('profile_ref') or ref(prop['output_profiles'][0], 'profile')
                profile = next((p for p in profiles if ref(p, 'profile') == reference), None)
                if profile is None:
                    raise ValueError('样例的输出配置版本已变化，请重新选择输出配置后校验')
                source = Representation.model_validate(example['source_representation'])
                source_value = bounded_decimal(example['source_value'])
                expected = bounded_decimal(example['expected_value'])
                for representation in (example['source_representation'], profile['representation']):
                    for field in ('scale', 'offset', 'reference_value'):
                        if representation.get(field) is not None:
                            bounded_decimal(representation[field])
                if source.kind != 'linear' and abs((source_value - bounded_decimal(source.offset)) / bounded_decimal(source.scale)) > 1000:
                    raise ValueError('Logarithmic exponent exceeds supported bound')
                policy = policies[key(profile['conversion_policy_ref'])]
                permission = conversion_permission(policy, {'value': {'kind': 'real'}, 'unit': example['source_unit']}, profile, source)
                if not permission['allowed']:
                    raise ValueError('所选来源策略未授权此转换；用户定义可明确选择“用户声明：同一科学量的现有转换”后重新校验')
                transform = SameQuantityTransform(source, Representation.model_validate(profile['representation']),
                    example['source_unit'], output_coordinate_unit(profile),
                    source_quantity_key=prop['definition']['quantity_key'], target_quantity_key=prop['definition']['quantity_key'])
                actual = transform.apply(source_value)
                report.update(actual_value=str(actual), expected_value=str(expected), profile_ref=reference)
                if actual != expected:
                    raise ValueError('预期值与现有转换引擎的计算结果不一致')
                checked_profiles.add(key(reference))
            except (DomainError, ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
                message = str(exc) if any('\u4e00' <= c <= '\u9fff' for c in str(exc)) else '样例无法由现有转换引擎核验，请检查数值范围、单位、表示和策略'
                report.update(state='failed', reason=message, detail=str(exc))
                errors.append({'code': 'USER_EXECUTION_EXAMPLE_FAILED', 'id': prop['id'], 'message': message, 'detail': str(exc)})
            reports.append(report)
        failed = any(r['state'] == 'failed' for r in reports) or not valid
        ready = valid and not failed
        normalization = ready and (bool(builtin) or prop['definition']['value_schema']['kind'] not in {'real', 'integer'} or bool(checked_profiles))
        cap = {'schema_version': 'user-property-capabilities/1', 'origin': origin, 'label': prop['label'],
            **{name: {'ready': ready, 'reasons': [] if ready else ['定义或输出配置未通过校验']} for name in ('retrieval', 'extraction', 'native')},
            'normalization': {'ready': normalization, 'reasons': [] if normalization else ['尚未验证转换样例；保留原始数据']},
            'validation': {'state': 'failed' if failed else 'passed', 'checks': [{'code': 'typed_definition', 'state': 'passed' if valid else 'failed'}], 'examples': reports}}
        capabilities[prop['id']] = cap
        if builtin or not ready:
            continue
        applicable = sorted([deepcopy(b) for b in (local_bindings if unchanged else by_property.get(prop['id'], [])) if b['property_key'] == prop['id'] and b['status'] == 'active'], key=lambda b: b['id'])
        dictionary_refs = []
        requested = {'family_id': {prop['family_id']}, 'subject_class_id': {prop['definition']['subject_class_id']},
                     'object_scale_id': {p['object_scale_id'] for p in profiles}}
        for role, identity in [('families', 'family_id'), ('subject-classes', 'subject_class_id'), ('object-scales', 'object_scale_id')]:
            for item in release['data'].get(role, []):
                if item[identity] in requested[identity]:
                    dictionary_refs.append({'id': item[identity], 'version': item['version'], 'content_sha256': item['content_sha256']})
        from .workspace_release import type_hash
        type_refs = {}
        for binding in applicable:
            target = projection['types'].get(binding['type_id'])
            while target and target['id'] not in type_refs:
                type_refs[target['id']] = {'id': target['id'], 'version': target['revision'], 'content_sha256': type_hash(target)}
                target = projection['types'].get(target.get('parent_id'))
        contract = {'schema_version': PROTOCOL, 'property_key': prop['id'], 'origin': origin,
            'definition_ref': prop['definition_ref'], 'definition': prop['definition'],
            'output_profiles': profiles, 'applicability': applicable,
            'local_conversion_policy': local_policy,
            'dictionary_refs': sorted(dictionary_refs, key=key),
            'applicability_type_refs': sorted(type_refs.values(), key=key),
            'source_definition_refs': deepcopy(prop.get('source_refs', [])),
            'validated_profile_refs': sorted(checked_profiles), 'capabilities': deepcopy(cap),
            'software_protocol': {'normalization_math': MATH_POLICY},
            'scientific_review_granted': False, 'authorization': 'user_declared_local_publication'}
        contract['content_sha256'] = content_hash(contract)
        reference = {'id': 'user-execution-' + prop['id'], 'version': prop['revision'], 'content_sha256': contract['content_sha256']}
        cap['execution_ref'] = reference
        contracts[key(reference)] = {'reference': reference, 'contract': contract}
    manifest = {'schema_version': PROTOCOL, 'contracts': contracts}
    manifest['content_sha256'] = content_hash(manifest)
    return manifest, capabilities, errors


def execution_binding(release, binding, prop):
    manifest = release.get('workspace', {}).get('execution_manifest')
    if not manifest:
        return None
    entry = next((e for e in manifest['contracts'].values() if e['contract']['property_key'] == prop['id']), None)
    if not entry or binding not in entry['contract']['applicability']:
        return None
    profiles = [*prop['output_profiles'], *([binding['output_profile']] if binding.get('output_profile') else [])]
    output = next(p for p in profiles if ref(p, 'profile') == binding['profile_ref'])
    contract = entry['contract']; reference = entry['reference']
    cap = deepcopy(contract['capabilities']); cap['execution_ref'] = reference
    if prop['definition']['value_schema']['kind'] in {'real', 'integer'} and key(binding['profile_ref']) not in contract['validated_profile_refs']:
        cap['normalization'] = {'ready': False, 'reasons': ['此输出配置尚无通过的转换样例']}
    applicability_ref = {'id': binding['id'], 'version': binding['revision'], 'content_sha256': digest(binding)}
    return {'property_id': prop['property_id'], 'definition': deepcopy(prop['definition']), 'output_profile': deepcopy(output),
        'dependency_refs': [prop['definition_ref'], binding['profile_ref'], output['conversion_policy_ref'], reference, applicability_ref, *contract['dictionary_refs'], *contract['applicability_type_refs']],
        'rule_refs': [applicability_ref], 'user_execution_ref': reference, 'execution_capabilities': cap,
        'authorization_origin': contract['origin']}


def verified_user_bindings(app, spec):
    """Resolve exact frozen bindings against their immutable release, never active defaults."""
    from .workspace_release import release_ref
    release = app.registry.load(spec['registry_release']['id'])
    if release_ref(release) != spec['registry_release']:
        raise DomainError('USER_EXECUTION_STALE', 'Frozen execution release changed')
    projection = release.get('workspace', {}).get('projection', {})
    verified = set()
    for frozen in spec['properties']:
        if not frozen.get('user_execution_ref'):
            continue
        matches = [execution_binding(release, b, projection['properties'][b['property_key']])
                   for b in projection.get('bindings', {}).values()]
        if not any(b and all(frozen.get(k) == b.get(k) for k in
                ('property_id', 'definition', 'output_profile', 'dependency_refs', 'rule_refs', 'user_execution_ref', 'execution_capabilities')) for b in matches):
            raise DomainError('USER_EXECUTION_STALE', 'User execution contract or frozen dependencies changed')
        verified.add(frozen['property_id'])
    return verified
