"""Version-one UI predicates shared by page reads and export selection.

These only match saved display coordinates and reported classifications. They
never change a measurement or infer scientific quality from its numeric value.
"""
import re

from astroquery_ai.runtime.errors import DomainError


DEFAULT_FILTERS = {'q': '', 'quick': 'all', 'field': 'all', 'source_id': 'all',
                   'year_sort': 'none', 'record_id': None, 'source_group': 'all'}
EXTRACTION_LABELS = {'paper': '论文提取', 'catalog': '星表提取', 'database': '数据库查询',
    'database_query': '数据库查询', 'csv_parsing': 'CSV 解析', 'llm_text': 'LLM 文本',
    'llm_table': 'LLM 表格', 'vlm_pdf': 'VLM PDF', 'vlm_text': 'VLM 文本',
    'vlm_table': 'VLM 表格', 'vlm_figure': 'VLM 图像'}


def normalize_filters(filters=None):
    if filters is None:
        filters = {}
    if not isinstance(filters, dict) or set(filters) - {*DEFAULT_FILTERS, 'fields'}:
        raise DomainError('INVALID_RESULT_FILTER', '结果筛选协议无效', 422)
    result = {**DEFAULT_FILTERS, **filters}
    for key, value in result.items():
        if key == 'fields':
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise DomainError('INVALID_RESULT_FILTER', '性质筛选必须是文本列表', 422)
        elif value is None and key in {'record_id', 'source_id'}:
            continue
        elif not isinstance(value, str):
            raise DomainError('INVALID_RESULT_FILTER', '筛选参数必须是文本', 422)
    if (result['quick'] not in {'all', 'target', 'modified', 'duplicate'}
            or result['year_sort'] not in {'none', 'asc', 'desc'}
            or result['source_group'] not in {'all', 'database', 'paper', 'supplement'}):
        raise DomainError('INVALID_RESULT_FILTER', '不支持此结果筛选或排序', 422)
    result['q'] = result['q'].strip().lower()
    return result


def journal_label(identifier):
    if not isinstance(identifier, str) or not re.match(r'^\d{4}', identifier):
        return identifier or ''
    code = identifier[4:9].rstrip('. ').strip()
    return f"{ {'Nat': 'Nature', 'Sci': 'Science'}.get(code, code)} {identifier[:4]}".strip()


def source_name(source, identifier):
    title = source.get('title')
    if title:
        return '；'.join(title) if isinstance(title, list) else title
    work = (source.get('work') or {}).get('records') or [{}]
    titles = work[0].get('titles') or []
    if titles:
        return titles[0]
    if re.match(r'^(?:work|source|material)-[0-9a-f-]{16,}$', identifier or '', re.I):
        return '来源资料'
    return journal_label(identifier) or '来源未提供'


def source_year(source):
    """Match readSources' nested work year ?? top-level year precedence."""
    records = (source.get('work') or {}).get('records') or []
    nested = records[0].get('year') if records and isinstance(records[0], dict) else None
    return nested if nested is not None else source.get('year')


def value_text(value):
    if value is None:
        return '未记录'
    kind = value.get('kind')
    if kind == 'interval':
        bounds = f"{value.get('lower') if value.get('lower') is not None else '−∞'}, {value.get('upper') if value.get('upper') is not None else '+∞'}"
        if type(value.get('lower_closed')) is bool and type(value.get('upper_closed')) is bool:
            return ('[' if value['lower_closed'] else '(') + bounds + (']' if value['upper_closed'] else ')')
        return bounds + '（边界开闭未记录）'
    if kind == 'boolean':
        return '是' if value.get('value') is True else '否' if value.get('value') is False else '未记录'
    if kind == 'category':
        return str(value['raw_label'] if value.get('raw_label') is not None else
                   value['code'] if value.get('code') is not None else '未记录')
    if kind == 'relation':
        name = (value.get('other_entity') or {}).get('raw_name')
        return str(name if name is not None else '关系对象未记录')
    return str(value['value'] if value.get('value') is not None else '未记录')


def record_coordinates(row):
    """Mirror the existing UI adapter's declared value/label search fields."""
    source = row['source']
    binding = row['property_binding']
    derived = row.get('derived') or {}
    ready = derived.get('main_state') == 'ready'
    profile = binding['output_profile']
    unit = profile['unit'] if ready else (source.get('unit_declaration') or {})
    dimensionless = unit.get('kind') == 'dimensionless'
    native_unit = (unit.get('canonical_symbol', '1' if dimensionless else '') if ready
                   else source.get('unit') if source.get('unit') is not None else unit.get('canonical_symbol'))
    if ready and native_unit is None:
        native_unit = '1' if dimensionless else ''
    representation = profile['representation'].get('kind') if ready else source.get('representation')
    is_coordinate = isinstance(native_unit, str) and (
        re.match(r'^dex(?:\b|$)|^(?:log(?:10)?|ln)\s*\(', native_unit.strip(), re.I)
        or native_unit.strip() == '[Fe/H]')
    shown_unit = native_unit
    if representation in {'log10', 'ln'} and not is_coordinate:
        shown_unit = (f'{representation}（无量纲原生坐标）' if dimensionless and native_unit == '1'
                      else f"{representation}（{native_unit or '参考单位未明确'}基准）")
    limit = derived.get('limit') if ready and derived.get('limit') is not None else source.get('limit')
    display = {'upper': '上限 ', 'lower': '下限 '}.get(limit, '') + value_text(
        derived.get('value_typed') if ready else source.get('value'))
    return {'record_id': source['measurement_id'], 'field_name': binding['definition']['name_cn'],
        'property_id': binding['property_id'], 'entity_name': row.get('target', {}).get('main_id') or
        (source.get('target_ref') or {}).get('id'), 'field_value': display, 'field_unit': shown_unit,
        'source_id': source['source_ref']['id'], 'extraction_method': source.get('source_kind')}


def search_fields(record, source):
    from astroquery_ai.application.legacy_property_labels import LABELS
    method = record.get('extraction_method')
    sid = record.get('source_id')
    # Separators cannot create matches across adjacent fields.
    return '\x00'.join(str(value).lower() for value in (
        record.get('record_id'), record.get('entity_name'), record.get('field_name'), LABELS.get(record.get('field_name')),
        record.get('field_value'), record.get('field_unit'), sid, source_name(source, sid),
        journal_label(sid), source.get('journal'), source_year(source), method,
        EXTRACTION_LABELS.get(method, method or '该记录未提供')) if value is not None)


def source_group(source, method=None):
    # Native exports classify their explicitly saved source kind; legacy rows
    # use the source directory and its historical ID-prefix fallback.
    kind = method if method in {'catalog', 'paper', 'official_attachment'} else source.get('source_type') or source.get('kind')
    if not kind:
        sid = source.get('source_id', '')
        kind = 'supplementary' if sid.startswith('SRC_SUPPL') else 'database' if sid.startswith('SRC_DB') else 'paper'
    if kind in {'db', 'database', 'catalog', 'database_query'}:
        return 'database'
    if kind in {'supplement', 'supplementary', 'official_attachment'}:
        return 'supplement'
    return 'paper'


def sql_predicate(filters):
    filters = normalize_filters(filters)
    clauses, args = [], []
    if filters['quick'] != 'all':
        clauses.append('excluded=0')
        if filters['quick'] in {'modified', 'duplicate'}:
            clauses.append(filters['quick'] + '=1')
    for field, column in [('field', 'field'), ('source_id', 'source_id'), ('record_id', 'record_id'),
                          ('source_group', 'source_group')]:
        if filters[field] not in {None, 'all'}:
            clauses.append(column + '=?')
            args.append(filters[field])
    if 'fields' in filters:
        clauses.append('field IN (' + ','.join('?' for _ in filters['fields']) + ')')
        args.extend(filters['fields'])
    if filters['q']:
        clauses.append('instr(search_text,?)>0')
        args.append(filters['q'])
    return ' AND '.join(clauses) or '1', args
