"""Finite declarative validation; no scientific approval is manufactured here."""
from pydantic import ValidationError
from astroquery_ai.runtime.errors import DomainError
from .models import Unit, Representation, ValueSchema, ConditionSchema
from .compiler import condition_variables
from .workbench_projection import ref


def validate_projection(projection, capabilities):
    errors, warnings = [], []
    def error(code, identifier, message):
        errors.append({'code': code, 'id': identifier, 'message': message})
    subjects = {x['id'] for x in capabilities['subjects']}
    scales = {x['id'] for x in capabilities['scales']}
    policies = {(x['policy_id'], str(x['version']), x['content_sha256']) for x in capabilities['conversion_policies']}
    quantity_keys = {}
    for item in projection['types'].values():
        if item['status'] != 'active':
            continue
        seen = set(); cursor = item
        while cursor and cursor['id'] != cursor.get('standard_otype'):
            if cursor['status'] != 'active':
                error('TYPE_PARENT_REQUIRED', item['id'], '父链包含已禁用类型'); break
            if cursor['id'] in seen:
                error('TYPE_CYCLE', item['id'], '父类型链存在循环'); break
            seen.add(cursor['id']); cursor = projection['types'].get(cursor.get('parent_id'))
        if not cursor or cursor['status'] != 'active' or cursor['id'] != item['standard_otype']:
            error('TYPE_PARENT_REQUIRED', item['id'], '父类型链缺少有效官方锚点')
        for condition in item.get('conditions', []):
            try:
                condition_variables(condition)
            except DomainError as exc:
                error(exc.code, item['id'], exc.message)
    for prop in projection['properties'].values():
        if prop['status'] != 'active':
            continue
        identifier = prop['id']; d = prop['definition']
        if subjects and d['subject_class_id'] not in subjects:
            error('INVALID_SUBJECT', identifier, '未知科学主体')
        identity = d['quantity_key']
        prior = quantity_keys.get(identity)
        source_pair = bool(prior) and all(p.get('source_quantity_identity') == {'property_id': p['property_id'], 'quantity_key': p['definition']['quantity_key']} for p in (prior, prop))
        if prior and prior['property_id'] != prop['property_id'] and not source_pair:
            error('DUPLICATE_QUANTITY_IDENTITY', identifier, '同一科学量身份已有性质')
        quantity_keys[identity] = prop
        try:
            ValueSchema.model_validate(d['value_schema'])
            for c in d.get('measurement_conditions_schema', []):
                ConditionSchema.model_validate(c)
        except ValidationError:
            error('INVALID_DEFINITION', identifier, '数值或测量条件结构无效')
        if not prop['output_profiles']:
            error('OUTPUT_PROFILE_REQUIRED', identifier, '至少需要一个输出配置')
        for profile in prop['output_profiles']:
            validate_profile(profile, d, identifier, error, scales, policies, prop.get('original_unit'))
        if not prop.get('automatic_conversion_ready'):
            warnings.append({'code': 'USER_DECLARED_EXECUTION', 'id': identifier,
                'message': '用户声明与科学审定分开；数值转换以服务器示例校验及发布契约为准，原始来源始终保留'})
    for binding in projection['bindings'].values():
        if binding['status'] != 'active':
            continue
        identifier = binding['id']; prop = projection['properties'].get(binding['property_key']); target = projection['types'].get(binding['type_id'])
        if not prop or not target or prop['status'] != 'active' or target['status'] != 'active':
            error('INVALID_BINDING_DEPENDENCY', identifier, '绑定依赖不存在或已禁用'); continue
        profiles = [*prop['output_profiles'], *([binding['output_profile']] if binding.get('output_profile') else [])]
        if binding['definition_ref'] != prop['definition_ref'] or not any(ref(p, 'profile') == binding['profile_ref'] for p in profiles):
            error('INVALID_EXACT_REFERENCE', identifier, '性质或输出配置精确引用不一致')
        if binding.get('output_profile'):
            if ref(binding['output_profile'], 'profile') != binding['profile_ref']:
                error('INVALID_EXACT_REFERENCE', identifier, '当前类型的输出配置与精确引用不一致，请明确恢复共享配置')
            validate_profile(binding['output_profile'], prop['definition'], identifier, error, scales, policies)
        for condition in binding.get('conditions', []) + binding.get('excluded_conditions', []):
            try:
                condition_variables(condition)
            except DomainError as exc:
                error(exc.code, identifier, exc.message)
    return errors, warnings


def validate_profile(profile, definition, identifier, error, scales, policies, original_unit=None):
    try:
        unit = Unit.model_validate(profile['unit']); representation = Representation.model_validate(profile['representation'])
        numeric = definition['value_schema']['kind'] in {'real', 'integer'}
        if numeric == (unit.kind == 'not_applicable') or numeric and representation.kind not in {'linear', 'log10', 'ln', 'magnitude'} or not numeric and representation.kind != definition['value_schema']['kind']:
            error('VALUE_REPRESENTATION_CONFLICT', identifier, '值类型、单位与表示方式不匹配')
        if scales and profile.get('object_scale_id') not in scales:
            error('INVALID_SCALE', identifier, '未知对象尺度')
        policy = profile.get('conversion_policy_ref', {})
        if (not {'id', 'version', 'content_sha256'} <= policy.keys()
                or (policy['id'], str(policy['version']), policy['content_sha256']) not in policies):
            error('INVALID_POLICY', identifier, '转换策略完整引用不在现有能力范围内')
        if unit.kind == 'physical' and unit.parser_format != 'source_literal' and not profile.get('review_ref'):
            from astropy import units
            parsed = units.Unit(unit.canonical_symbol, format=unit.parser_format)
            for declared in (unit.dimension, definition.get('quantity_kind')):
                try:
                    dimension = units.get_physical_type(declared)
                except (ValueError, TypeError):
                    continue  # Source-specific scientific labels are not unit dimensions.
                if str(dimension) != 'unknown' and parsed.physical_type != dimension:
                    error('UNIT_DIMENSION_CONFLICT', identifier, '单位与声明的科学量维度不一致，请修正单位或新建正确性质')
            if original_unit and original_unit.get('parser_format') != 'source_literal':
                original = units.Unit(original_unit['canonical_symbol'], format=original_unit['parser_format'])
                if not parsed.is_equivalent(original):
                    error('UNIT_DIMENSION_CONFLICT', identifier, '单位改变了科学量维度，请新建性质')
        if unit.kind == 'physical' and unit.parser_format == 'source_literal':
            # Source-literal symbols remain descriptive and cannot grant a new parser.
            if not profile.get('review_ref'):
                error('INVALID_UNIT', identifier, '新增物理单位必须可由现有单位解析器核验')
    except (ValidationError, ValueError, KeyError, TypeError):
        error('INVALID_UNIT', identifier, '单位或表示参数不可核验')
