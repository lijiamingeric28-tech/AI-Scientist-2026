"""Versioned research files projected from one delivery, never new science.

Typed coordinates and independent error components are copied, not inferred.
Large evidence/knowledge objects are stored once in JSON/ZIP, never per CSV row.
"""
from __future__ import annotations

import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation

from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.runtime.errors import DomainError

VERSION = 2
FIELDS = (
    'measurement_id', 'target', 'component', 'property_name', 'property_id',
    'value', 'value_kind', 'value_origin', 'unit', 'representation', 'limit',
    'lower_bound', 'upper_bound', 'lower_closed', 'upper_closed', 'text_value', 'error_minus', 'error_plus',
    'error_unit', 'error_kind', 'error_role', 'confidence_level',
    'uncertainty_state', 'uncertainty_component_count', 'raw_value',
    'source_numeric_value', 'source_unit', 'source_representation',
    'source_type', 'source_title', 'source_id', 'physical_pages',
    'table', 'row', 'column', 'figure', 'method', 'result_role',
    'context', 'processing_status', 'record_status', 'review_status',
    'evidence_ids', 'original_url', 'evidence_locations_json',
    'uncertainty_components_json', 'export_schema_version', 'delivery_id',
    'delivery_revision', 'snapshot_id', 'snapshot_sha256', 'selected_count',
)
COORDINATE_FIELDS = ('native_epoch', 'native_epoch_column', 'native_epoch_unit',
                     'native_epoch_definition', 'native_band', 'native_coordinates_json')


def numeric(value):
    """Only already typed finite scalars; never parse printed mixed notation."""
    if isinstance(value, bool) or value is None:
        return ''
    try:
        return str(value) if Decimal(str(value)).is_finite() else ''
    except (InvalidOperation, ValueError):
        return ''


def text(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return '; '.join(text(v) for v in value)
    if isinstance(value, dict):
        return canonical(value).decode()
    return str(value)


def csv_bytes(rows, fields):
    from .exporting import csv_display
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fields, extrasaction='raise')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_display(row.get(key, ''))[0] for key in fields})
    return stream.getvalue().encode('utf-8-sig')


def metadata(body):
    selected = body.get('export_selection', {}).get('selected_ids')
    if selected is None:
        selected = sorted(m['measurement_id'] for m in body['measurements'])
    return {'export_schema_version': body.get('export_metadata', {}).get('export_schema_version', VERSION),
        'delivery_id': body['delivery_id'],
        'delivery_revision': body['revision'], 'snapshot_ref': body['snapshot_ref'],
        'selected_ids': selected, 'selected_count': len(selected),
        'report_scope': 'Task-level summaries describe the whole frozen task, not just selected rows.',
        'insight_ref': body.get('insight', {}).get('report_ref'),
        'quality_ref': body.get('quality', {}).get('report_ref')}


def artifact_url(body, artifact_id, page=None):
    config = body.get('export_metadata', {})
    tid = config.get('resource_task_id', body['task_id'])
    url = config.get('origin', '').rstrip('/') + f'/api/tasks/{tid}/artifacts/{artifact_id}'
    return url + (f'#page={page}' if isinstance(page, int) else '')


def source_rows(body):
    return [{**s, 'original_url': artifact_url(body, s['artifact']['artifact_id'])
            if s.get('artifact', {}).get('artifact_id') else None,
            'original_in_package': False} for s in body.get('sources', [])]


def locations(body, record, evidence, sources=None):
    from ..evidence_views import attachment_location
    result = []
    for ref in record.get('evidence_refs', []):
        item = evidence.get(ref['id'])
        if item is None:
            continue
        locator = item.get('locator') or {}
        aid = (item.get('artifact_ref') or {}).get('id')
        source = (sources or {}).get(item.get('source_id'), {})
        result.append({'evidence_id': ref['id'], 'source_id': item.get('source_id'),
            'kind': item.get('kind'), **locator,
            **({'attachment_location': attachment_location(source)}
               if source.get('kind') == 'official_attachment' or source.get('official_supplement') else {}),
            'original_url': artifact_url(body, aid, locator.get('page')) if aid else None})
    return result


def uncertainty_rows(record, derived, unit_records, source_unit, output_unit):
    """Retain each component and the exact conversion outcome independently."""
    converted = {x.get('source_component_id'): x
                 for x in ((derived or {}).get('uncertainty_typed') or {}).get('components', [])}
    results = []
    for component in record['uncertainty']['components']:
        state = converted.get(component['component_id'], {})
        output = state.get('output_component')
        source_declaration = unit_records.get((component.get('unit_ref') or {}).get('id'), {})
        native_unit = source_declaration.get('unit_text')
        if native_unit is None:
            native_unit = (source_declaration.get('unit_declaration') or {}).get('canonical_symbol')
        # A missing error-unit declaration is unknown, not automatically the
        # main unit: percentages, covariance, and log errors may differ.
        result = {'measurement_id': record['measurement_id'],
            'component_id': component['component_id'], 'source_component': component,
            'source_unit': native_unit, 'processing_status': state.get('status', 'not_run'),
            'processed_component': output,
            'processed_unit': output_unit if output is not None else None}
        results.append(result)
    return results


def main_error(details, using_processed):
    """Expose a single delta without combining independent components."""
    if len(details) != 1:
        return {}
    detail = details[0]
    processed = detail['processed_component'] if using_processed else None
    component = processed or detail['source_component']
    unit = detail['processed_unit'] if processed is not None else detail['source_unit']
    if component.get('interpretation_state') != 'parsed':
        return {}
    values = component.get('values') or {}
    if component.get('kind') == 'symmetric_delta':
        minus = plus = numeric(values.get('delta'))
    elif component.get('kind') == 'asymmetric_delta':
        minus, plus = numeric(values.get('minus')), numeric(values.get('plus'))
    else:
        return {}
    return {'error_minus': minus, 'error_plus': plus, 'error_unit': unit or '',
            'error_kind': component['kind'], 'error_role': component.get('role') or '',
            'confidence_level': text(component.get('level'))}


def tables(body):
    definitions = {b['property_id']: b for b in body['definitions']}
    outputs = {d['measurement_id']: d for d in body['derived']}
    sources = {s['source_id']: s for s in body['sources']}
    evidence = {e['evidence_id']: e for e in body['evidence_index']}
    contexts = {c['measurement_ref']['id']: c for c in body['contexts']}
    contexts.update({c['measurement_ref']['id']: c for c in body.get('resolved_contexts', [])})
    provenance = body.get('provenance_bundle', {})
    interpretations = {i['interpretation_id']: i for i in provenance.get('interpretations', [])}
    units = {u['unit_id']: u for u in provenance.get('unit_records', [])}
    statements = {s['statement_id']: s for s in provenance.get('source_statements', [])}
    from astroquery_ai.application.result_views import report_dispositions, record_status
    annotations = report_dispositions(body)
    meta = metadata(body)
    common = {'export_schema_version': meta['export_schema_version'], 'delivery_id': body['delivery_id'],
        'delivery_revision': body['revision'], 'snapshot_id': body['snapshot_ref']['id'],
        'snapshot_sha256': body['snapshot_ref']['content_sha256'], 'selected_count': meta['selected_count']}
    rows, errors, location_index = [], [], []
    for record in body['measurements']:
        mid = record['measurement_id']; pid = record['property_ref']['id']
        binding = definitions[pid]; output = outputs.get(mid, {})
        processed = output.get('main_state') == 'ready' and output.get('value_typed') is not None
        value = output['value_typed'] if processed else record['value']
        profile = binding['output_profile']
        unit = output.get('coordinate_units', {}).get('target') if processed else record['unit']
        if processed and unit is None:
            unit = profile['unit'].get('canonical_symbol') or ''
        context = contexts.get(mid, {})
        known = [c for c in context.get('conditions', []) if c.get('state') == 'known']
        interpretation = interpretations.get(record.get('interpretation_ref', {}).get('id'), {})
        proposal = interpretation.get('proposal', {})
        source = sources.get(record['source_ref']['id'], {})
        own_statements = [statements[ref['id']] for ref in context.get('source_statements', []) if ref['id'] in statements]
        detail = uncertainty_rows(record, output, units, record['unit'], unit)
        errors.extend(detail)
        loc = locations(body, record, evidence, sources)
        location_index.append({'measurement_id': mid, 'locations': loc})
        def unique(key):
            return '; '.join(dict.fromkeys(text(x[key]) for x in loc if x.get(key) is not None))
        row = {**common, 'measurement_id': mid, 'target': body['target']['main_id'],
            'component': '; '.join(text(c['value']) for c in known if c['key'] in {'physical_subject_binding', 'component', 'subject_component', 'region'}),
            'property_name': binding['definition']['name_cn'], 'property_id': pid,
            'value': numeric(value.get('value')) if value['kind'] in {'real', 'integer'} else '',
            'value_kind': value['kind'], 'value_origin': 'processed' if processed else 'source',
            'unit': unit, 'representation': (profile.get('representation', {}).get('kind') or record['representation']) if processed else record['representation'],
            'limit': output.get('limit', record.get('limit')) if processed else record.get('limit'),
            'lower_bound': numeric(value.get('lower')), 'upper_bound': numeric(value.get('upper')),
            'lower_closed': value.get('lower_closed', ''), 'upper_closed': value.get('upper_closed', ''),
            'text_value': value.get('value', value.get('raw_label', '')) if value['kind'] in {'text', 'category', 'boolean'} else canonical(value).decode() if value['kind'] == 'relation' else '',
            **main_error(detail, processed), 'uncertainty_state': record['uncertainty']['state'],
            'uncertainty_component_count': len(detail), 'raw_value': record['raw_value'],
            'source_numeric_value': numeric(record['value'].get('value')) if record['value']['kind'] in {'real', 'integer'} else '',
            'source_unit': record['unit'], 'source_representation': record['representation'],
            'source_type': record['source_kind'], 'source_title': text(source.get('title')),
            'source_id': record['source_ref']['id'], 'physical_pages': unique('page'),
            'table': unique('table'), 'row': unique('row'), 'column': unique('column'),
            'figure': unique('figure'), 'method': '; '.join(s.get('text', '') for s in own_statements if s.get('kind') == 'method'),
            'result_role': proposal.get('result_role') or interpretation.get('result_role', ''),
            'context': '; '.join(f"{c['key']}: {text(c.get('value'))}" for c in known),
            'processing_status': output.get('status', 'not_run'),
            'record_status': record_status(record, annotations),
            'review_status': 'human_reviewed' if interpretation.get('human_answer_ref') else '',
            'evidence_ids': '; '.join(r['id'] for r in record.get('evidence_refs', [])),
            'original_url': next((x['original_url'] for x in loc if x.get('original_url')), ''),
            'evidence_locations_json': canonical(loc).decode(),
            'uncertainty_components_json': canonical(detail).decode()}
        fields = FIELDS
        if meta['export_schema_version'] == 3:
            from .native_coordinates import table_coordinates
            coordinates = table_coordinates(record, evidence)
            epoch = coordinates['epochs'][0] if len(coordinates['epochs']) == 1 else {}
            band = coordinates['bands'][0] if len(coordinates['bands']) == 1 else {}
            row.update(native_epoch=epoch.get('value'), native_epoch_column=epoch.get('column'),
                       native_epoch_unit=epoch.get('unit'), native_epoch_definition=epoch.get('definition'),
                       native_band=band.get('value'),
                       native_coordinates_json=canonical(coordinates).decode() if any(coordinates.values()) else '')
            fields += COORDINATE_FIELDS
        rows.append({key: row.get(key, '') for key in fields})
    return rows, errors, location_index


def wide_rows(body, rows, coordinates=None):
    """A common source alone never licenses pairing.

    Accept only a producer's explicit, evidence-backed joint observation/model
    group. Unknown grouping stays one row per record, preserving all records.
    """
    by_id = {r['measurement_id']: r for r in rows}
    evidence_ids = {e['evidence_id'] for e in body.get('evidence_index', [])}
    used = set(); groups = []
    for group in body.get('joint_measurement_groups', []):
        ids = group.get('measurement_ids', [])
        if (group.get('basis') not in {'same_observation', 'same_model_fit'}
                or not group.get('evidence_refs') or not group.get('group_id')
                or any(ref.get('id') not in evidence_ids for ref in group.get('evidence_refs', []))
                or len(ids) != len(set(ids)) or set(ids) & used):
            continue
        own = [by_id[mid] for mid in ids if mid in by_id]
        if not own or len({r['property_id'] for r in own}) != len(own):
            continue
        # A producer cannot pair records from different target identities.
        if len({r['target'] for r in own}) != 1:
            continue
        groups.append((group['group_id'], group['basis'], own)); used.update(r['measurement_id'] for r in own)
    groups.extend((r['measurement_id'], 'unpaired_record', [r]) for r in rows if r['measurement_id'] not in used)
    fields = ['group_id', 'group_basis', 'target', 'delivery_id', 'delivery_revision', 'snapshot_id', 'snapshot_sha256', 'selected_count', 'export_schema_version']
    props = list(dict.fromkeys(r['property_id'] for r in rows))
    if coordinates is None:
        coordinates = ('measurement_id', 'value', 'unit', 'error_minus', 'error_plus', 'error_unit', 'limit',
                       'lower_bound', 'upper_bound', 'raw_value', 'source_id', 'processing_status', 'uncertainty_components_json')
    fields += [pid + ':' + key for pid in props for key in coordinates]
    result = []
    for gid, basis, own in groups:
        row = {k: own[0][k] for k in fields[:9] if k in own[0]}
        row.update(group_id=gid, group_basis=basis)
        for record in own:
            row.update({record['property_id'] + ':' + key: record[key] for key in coordinates})
        result.append(row)
    return result, fields


def serialize(body, format):
    meta = metadata(body)
    if format == 'json':
        return canonical({**body, 'export_metadata': {**body.get('export_metadata', {}), **meta}}), 'application/json'
    rows, errors, loc = tables(body)
    if format == 'csv_long':
        return csv_bytes(rows, FIELDS), 'text/csv'
    if format == 'csv_wide':
        wide, fields = wide_rows(body, rows)
        return csv_bytes(wide, fields), 'text/csv'
    if format == 'json_wide':
        outputs = {d['measurement_id']: d for d in body['derived']}
        contexts = {c['measurement_ref']['id']: c for c in body['contexts']}
        contexts.update({c['measurement_ref']['id']: c for c in body.get('resolved_contexts', [])})
        return canonical({'export_metadata': meta, 'properties': [{
            'property_id': b['property_id'], 'name': b['definition']['name_cn'],
            'definition_ref': {'id': b['property_id'], 'version': b['definition']['definition_version'], 'content_sha256': b['definition']['content_sha256']},
            'unit': b['output_profile']['unit'], 'representation': b['output_profile'].get('representation'),
            'records': [{'source': m, 'derived': outputs.get(m['measurement_id']),
                         'context': contexts.get(m['measurement_id'])}
                        for m in body['measurements'] if m['property_ref']['id'] == b['property_id']]}
            for b in body['definitions'] if any(m['property_ref']['id'] == b['property_id'] for m in body['measurements'])]}), 'application/json'
    if format != 'package':
        raise DomainError('UNSUPPORTED_EXPORT_FORMAT', '不支持此导出格式', 422)
    table = csv_bytes(rows, FIELDS)
    wide, fields = wide_rows(body, rows)
    dictionary = {key: key.replace('_', ' ') for key in FIELDS}
    dictionary.update(value='已经解析的数值坐标；仅处理完成时用处理值，否则保留源值，见value_origin。',
        error_minus='单个已解析误差分量的负向幅度，不合并分量；空白不是零。',
        error_plus='单个已解析误差分量的正向幅度；不补置信水平。',
        uncertainty_components_json='本记录全部独立分量、原报及实际处理状态；同errors.json按measurement_id关联。',
        physical_pages='PDF物理页，不是印刷页码；其他定位见evidence_locations_json。')
    files = {'measurements.csv': table, 'measurements-wide.csv': csv_bytes(wide, fields),
        'delivery.json': serialize(body, 'json')[0], 'properties.json': serialize(body, 'json_wide')[0],
        'errors.json': canonical(errors), 'sources.json': canonical(source_rows(body)),
        'evidence-locations.json': canonical(loc), 'column-dictionary.json': canonical(dictionary),
        'processing-and-review.json': canonical({'derived': body['derived'], 'dispositions': body.get('dispositions', []),
            'human_answers': body.get('provenance_bundle', {}).get('human_answers', []),
            'task_score': body.get('task_score'), 'task_report_scope': 'whole_task'}),
        'insights.json': canonical(body.get('insight_report', {})),
        'README.md': (f"# AstroQuery研究数据包（格式{VERSION}）\n\n选中{len(rows)}条；交付修订{body['revision']}。"
            "\n\n先打开measurements.csv，可按性质和数值排序。误差缺失为空白，多分量独立保存在errors.json；不平均、不补零。"
            "\n\n宽表只使用已有证据支持的共同观测/模型组；其余各占独立行，不因同论文强行配对。"
            "\n\n完整审计对象和大证据仅在delivery.json保存一次；properties.json提供轻量按性质读取。"
            "\n\n包内没有原PDF、原表文件或图像二进制。sources.json和evidence-locations.json给本地服务原件地址与页/行/列。"
            "离线阅读这些原件需另外保存；运行原服务后可点击CSV的original_url。"
            "\n\n任务评分与洞察摘要描述整个冻结任务，不能当作此次筛选子集的正确率。"
            "\n\nCSV中公式样式的文本已用前置单引号防执行；确切原文在JSON。\n").encode('utf-8')}
    files['manifest.json'] = canonical({**meta, 'files': {k: __import__('hashlib').sha256(v).hexdigest() for k, v in files.items()},
        'original_files_included': False, 'large_evidence_location': 'delivery.json'})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            # Export identity is snapshot/revision/selection based. Wall-clock
            # ZIP headers must not make an identical retry a different file.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return stream.getvalue(), 'application/zip'
