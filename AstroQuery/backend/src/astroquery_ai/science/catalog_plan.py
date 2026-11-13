"""Independently retain valid column groups; do not discard a whole mixed plan."""

from astroquery_ai.runtime.errors import DomainError


def response_schema(columns, properties, targets=None):
    field_list = {'type': 'array', 'items': {'$ref': '#/$defs/column'}, 'uniqueItems': True}
    mapping = {'type': 'object', 'additionalProperties': False,
        'required': ['property_id', 'value_column', 'error_columns', 'source_unit', 'source_representation'],
        'properties': {'property_id': {'enum': sorted(properties)},
            'value_column': {'$ref': '#/$defs/target_column'},
            'error_columns': field_list, 'context_columns': field_list, 'quality_columns': field_list,
            'reference_columns': field_list, 'limit_column': {'anyOf': [{'$ref': '#/$defs/column'}, {'type': 'null'}]},
            'source_unit': {'type': ['string', 'null']},
            'quantity_match': {'enum': ['exact', 'different', 'unresolved']},
            'source_representation': {'enum': ['linear', 'log10', 'ln', 'magnitude', 'category', 'boolean', 'text', 'relation']}}}
    root = {'type': 'object', 'additionalProperties': False,
        '$defs': {'column': {'enum': list(columns)}, 'target_column': {'enum': list(targets or columns)}},
        'required': ['id_column', 'identity_namespace', 'properties', 'limitations'],
        'properties': {'id_column': {'anyOf': [{'$ref': '#/$defs/column'}, {'type': 'null'}]},
            'identity_alias_ids': {'type':'array','items':{'type':'string'},'maxItems':3,'uniqueItems':True},
            'identity_namespace': {'type': ['string', 'null']},
            'properties': {'type': 'array', 'items': mapping}, 'limitations': {'type': 'array', 'items': {'type': 'string'}}}}
    if targets is not None:
        root['required'].append('column_resolution')
        root['properties']['column_resolution'] = {'type': 'array', 'items': {'type': 'object',
            'additionalProperties': False, 'required': ['column', 'role', 'reason'], 'properties': {
                'column': {'$ref': '#/$defs/target_column'}, 'role': {'enum': ['value', 'error', 'limit', 'context', 'reference', 'quality', 'identity', 'not_relevant', 'unresolved']},
                'reason': {'type': 'string', 'minLength': 1}}}}
    return root


def compatible_returned_plan(plan, planned_columns, returned_columns):
    """Reject stale field groups without losing independent unchanged groups."""
    expected, actual = ({c['name']: c for c in columns} for columns in [planned_columns, returned_columns])
    semantic = ('datatype', 'unit_text', 'ucd', 'arraysize', 'description', 'null', 'reference_context')

    def changes(name):
        if name not in expected or name not in actual:
            return ['column_missing']
        return [key for key in semantic if expected[name].get(key) != actual[name].get(key)]

    id_changes = changes(plan['id_column']) if plan['id_column'] is not None else []
    if id_changes:
        return {**plan, 'properties': []}, [{'reason': 'identifier_schema_changed', 'column': plan['id_column'], 'changed_fields': id_changes}]
    mappings, gaps = [], []
    for mapping in plan['properties']:
        names = {mapping['value_column'], *mapping['error_columns'], *mapping.get('context_columns', []),
                 *mapping.get('quality_columns', []), *mapping.get('reference_columns', [])}
        if mapping.get('limit_column'):
            names.add(mapping['limit_column'])
        altered = [{'column': name, 'changed_fields': changes(name)} for name in sorted(names) if changes(name)]
        if altered:
            gaps.append({'reason': 'field_group_schema_changed', 'property_id': mapping['property_id'],
                         'value_column': mapping['value_column'], 'columns': altered})
        else:
            mappings.append(mapping)
    return {**plan, 'properties': mappings}, gaps


def validate_column_resolution(raw, targets, mappings):
    """A partial response leaves explicit gaps, never an implicit full table pass."""
    if not isinstance(raw, list):
        raise DomainError('CATALOG_PLAN_INVALID', '宽表计划缺少逐字段解释数组')
    indexed, gaps = {}, []
    roles = {'value', 'error', 'limit', 'context', 'reference', 'quality', 'identity', 'not_relevant', 'unresolved'}
    for item in raw:
        if (not isinstance(item, dict) or set(item) != {'column', 'role', 'reason'}
                or not isinstance(item['column'], str) or item['column'] not in targets
                or not isinstance(item['role'], str) or item['role'] not in roles
                or not isinstance(item['reason'], str) or not item['reason'].strip()):
            gaps.append({'reason': 'invalid_column_resolution', 'raw_resolution': item})
            continue
        if item['column'] in indexed:
            indexed[item['column']] = {'column': item['column'], 'role': 'unresolved', 'reason': 'duplicate_resolution'}
        else:
            indexed[item['column']] = item
    for column in targets:
        if column not in indexed:
            indexed[column] = {'column': column, 'role': 'unresolved', 'reason': 'column_not_resolved_in_response'}
    value_columns = {m['value_column'] for m in mappings}
    for column, item in indexed.items():
        if (item['role'] == 'value') != (column in value_columns):
            indexed[column] = {'column': column, 'role': 'unresolved', 'reason': 'column_resolution_mapping_disagreement'}
        if indexed[column]['role'] == 'unresolved':
            gaps.append({'column': column, 'reason': indexed[column]['reason']})
    allowed = {column for column, item in indexed.items() if item['role'] == 'value'}
    return [indexed[column] for column in targets], [m for m in mappings if m['value_column'] in allowed], gaps


def validate_plan(raw, columns, allowed_properties):
    alias_ids=raw.get('identity_alias_ids') if isinstance(raw,dict) else None
    if isinstance(raw,dict) and 'identity_alias_ids' in raw:
        if not isinstance(alias_ids,list) or len(alias_ids)>3 or any(not isinstance(a,str) for a in alias_ids):
            raise DomainError('CATALOG_PLAN_INVALID','标识查询必须选择最多三个真实别名标签')
        checked,gaps=validate_plan({k:v for k,v in raw.items() if k!='identity_alias_ids'},columns,allowed_properties)
        return {**checked,'identity_alias_ids':alias_ids},gaps
    root = {"id_column", "identity_namespace", "properties", "limitations"}
    if (
        not isinstance(raw, dict)
        or set(raw) != root
    ):
        raise DomainError("CATALOG_PLAN_INVALID", "列计划根结构无效")
    if raw["identity_namespace"] is not None and not isinstance(raw["identity_namespace"], str):
        raise DomainError("CATALOG_PLAN_INVALID", "对象命名空间必须为有据字符串或null")
    if (
        not isinstance(raw["properties"], list)
        or not isinstance(raw["limitations"], list)
        or any(not isinstance(item, str) for item in raw["limitations"])
    ):
        raise DomainError("CATALOG_PLAN_INVALID", "星表计划结构无效")
    if raw["id_column"] is None and not raw["properties"]:
        return raw, []  # No requested quantity: no object-row lookup is needed.
    if raw['id_column'] is not None and (not isinstance(raw["id_column"], str) or raw["id_column"] not in columns):
        raise DomainError("CATALOG_PLAN_INVALID", "列计划缺少可验证的对象标识列")
    valid, gaps, seen = [], [], set()
    required = {
        "property_id",
        "value_column",
        "error_columns",
        "source_unit",
        "source_representation",
    }
    optional = {"context_columns", "quality_columns", "reference_columns", "limit_column", 'quantity_match'}
    for index, mapping in enumerate(raw["properties"]):
        if isinstance(mapping, dict):
            null_arrays = [k for k in ('error_columns', 'context_columns', 'quality_columns', 'reference_columns')
                if isinstance(mapping.get(k), list) and any(v is None for v in mapping[k])]
            if null_arrays:
                original_mapping = mapping
                mapping = {**mapping, **{k: [v for v in mapping[k] if v is not None] for k in null_arrays}}
                gaps.append({'mapping_index': index, 'reason': 'null_optional_column_placeholders_removed',
                             'state': 'protocol_normalized', 'fields': null_arrays, 'raw_mapping': original_mapping})
        reason = None
        if (
            not isinstance(mapping, dict)
            or not required <= set(mapping)
            or set(mapping) - required - optional
        ):
            reason = "column_mapping_schema"
        elif (
            not isinstance(mapping["property_id"], str)
            or mapping["property_id"] not in allowed_properties
            or not isinstance(mapping["value_column"], str)
            or mapping["value_column"] not in columns
        ):
            reason = "property_or_column_not_authorized"
        elif (
            mapping["source_unit"] is not None
            and not isinstance(mapping["source_unit"], str)
            or not isinstance(mapping["source_representation"], str)
            or mapping["source_representation"]
            not in {"linear", "log10", "ln", "magnitude", "category", "boolean", "text", "relation"}
        ):
            reason = "source_representation_schema"
        elif mapping.get('quantity_match') is not None and mapping['quantity_match'] not in {'exact', 'different', 'unresolved'}:
            reason = 'column_mapping_schema'
        else:
            for key in ("error_columns", "context_columns", "quality_columns", "reference_columns"):
                names = mapping.get(key, [])
                if (
                    not isinstance(names, list)
                    or any(not isinstance(name, str) or name not in columns for name in names)
                    or len(set(names)) != len(names)
                ):
                    reason = "linked_column_not_available"
                    break
            if mapping.get("limit_column") is not None and (
                not isinstance(mapping["limit_column"], str)
                or mapping["limit_column"] not in columns
            ):
                reason = "limit_column_not_available"
        if reason:
            gaps.append({"mapping_index": index, "reason": reason, "raw_mapping": mapping})
            continue
        key = (mapping["property_id"], mapping["value_column"])
        if key in seen:
            gaps.append(
                {
                    "mapping_index": index,
                    "reason": "duplicate_property_column_group",
                    "raw_mapping": mapping,
                }
            )
            continue
        seen.add(key)
        valid.append(mapping)
    return {**raw, "properties": valid}, gaps
