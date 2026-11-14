"""Exercise the five real serializers against the exact proposed snapshot."""
import csv,io,zipfile,json,hashlib
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from .exporting import _serialize


def verify_formats(body, *, export_schema_version=None):
    version = export_schema_version or body.get('export_schema_version', 1)
    if version == 2:
        return verify_research_formats(body)
    expected={m['measurement_id']:m for m in body['measurements']};formats={}
    csv_long = None
    for fmt in ('json','json_wide','csv_long','csv_wide','package'):
        if fmt == 'package':
            # The package embeds this exact body's CSV, already verified in
            # this call. Do not serialize the same large CSV a second time.
            raw,media=_serialize(body,fmt,_csv_long=csv_long)
        else:
            raw,media=_serialize(body,fmt)
        if fmt == 'csv_long':
            csv_long = raw
        if fmt=='package':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:decoded=json.loads(archive.read('delivery.json'))
            records=decoded['measurements'];snapshot=decoded['snapshot_ref']
        elif fmt=='json':
            decoded=json.loads(raw);records=decoded['measurements'];snapshot=decoded['snapshot_ref']
        elif fmt=='json_wide':
            decoded=json.loads(raw);records=[v['source'] for group in decoded['values'].values() for v in group]
            snapshot=decoded['metadata']['snapshot_ref']
        else:
            # These CSV fields are our already serialized immutable metadata,
            # not an unbounded external upload. Keep full definitions/evidence;
            # Python's unrelated 128 KiB default must not break publication.
            csv.field_size_limit(max(csv.field_size_limit(),len(raw)))
            rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            if fmt=='csv_long':records=[json.loads(row['source_measurement_json']) for row in rows]
            else:records=[v['source'] for row in rows for b in body['definitions']
                for v in json.loads(row.get(b['property_id']) or '[]')]
            snapshot=json.loads(rows[0]['snapshot_ref_json']) if rows else body['snapshot_ref']
        actual={m['measurement_id']:m for m in records}
        if canonical(actual)!=canonical(expected) or snapshot!=body['snapshot_ref'] or len(records)!=len(expected):
            raise DomainError('EXPORT_CONTENT_MISMATCH','交付序列化丢失或改变原报、误差及来源',format=fmt)
        formats[fmt]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'media_type':media,
            'source_records_verified':len(actual)}
    return {'schema_version':'DeliverySerializationCheck/1','snapshot_ref':body['snapshot_ref'],
        'delivery_id':body['delivery_id'],'state':'passed','formats':formats,'generator':'existing-five-serializers',
        'scope':'Exact source measurement including uncertainty and all references; same snapshot in every format'}


def verify_research_formats(body):
    """Verify the new projections against typed science, not just row counts."""
    from .exporting import csv_display
    expected = {m['measurement_id']: m for m in body['measurements']}
    outputs = {d['measurement_id']: d for d in body['derived']}
    formats, encoded = {}, {}

    def require(condition, fmt, field):
        if not condition:
            raise DomainError('EXPORT_CONTENT_MISMATCH', '新版导出未保持所选原报、误差或快照', format=fmt, field=field)

    def check_meta(meta, fmt):
        require(meta['snapshot_ref'] == body['snapshot_ref'] and meta['delivery_revision'] == body['revision']
            and meta['selected_ids'] == sorted(expected) and meta['selected_count'] == len(expected), fmt, 'snapshot_and_selection')

    for fmt in ('json', 'json_wide', 'csv_long', 'csv_wide', 'package'):
        raw, media = _serialize(body, fmt, export_schema_version=2)
        encoded[fmt] = raw
        if fmt == 'json':
            full = json.loads(raw)
            require(canonical(full['measurements']) == canonical(body['measurements']), fmt, 'source_measurements')
            require(canonical(full['derived']) == canonical(body['derived']), fmt, 'derived')
            require(canonical(full['evidence_index']) == canonical(body['evidence_index']), fmt, 'full_evidence')
            check_meta(full['export_metadata'], fmt)
        elif fmt == 'json_wide':
            grouped = json.loads(raw); check_meta(grouped['export_metadata'], fmt)
            records = [r for g in grouped['properties'] for r in g['records']]
            require(len(records) == len(expected) and {r['source']['measurement_id'] for r in records} == set(expected), fmt, 'record_set')
            require(all(r['source'] == expected[r['source']['measurement_id']] and
                r['derived'] == outputs.get(r['source']['measurement_id']) for r in records), fmt, 'source_and_derived')
        elif fmt == 'csv_long':
            csv.field_size_limit(max(csv.field_size_limit(), len(raw)))
            table = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            require(len(table) == len(expected) and {r['measurement_id'] for r in table} == set(expected), fmt, 'record_set')
            rows = {r['measurement_id']: r for r in table}
            for mid, source in expected.items():
                row = rows[mid]; output = outputs.get(mid, {})
                ready = output.get('main_state') == 'ready' and output.get('value_typed') is not None
                value = output['value_typed'] if ready else source['value']
                require(row['raw_value'] == csv_display(source['raw_value'])[0] and
                    row['source_unit'] == (csv_display(source['unit'])[0] if source['unit'] is not None else '') and
                    row['source_representation'] == source['representation'] and
                    row['source_type'] == source['source_kind'], fmt, mid + ':source')
                require(row['value_origin'] == ('processed' if ready else 'source') and
                    row['value_kind'] == value['kind'], fmt, mid + ':coordinate')
                if value['kind'] in {'real', 'integer'}:
                    require(row['value'] == value['value'], fmt, mid + ':scalar')
                else:
                    require(row['value'] == '', fmt, mid + ':non_scalar')
                if value['kind'] == 'interval':
                    require(row['lower_bound'] == (value['lower'] or '') and row['upper_bound'] == (value['upper'] or '') and
                        row['lower_closed'] == str(value['lower_closed']) and row['upper_closed'] == str(value['upper_closed']), fmt, mid + ':interval')
                details = json.loads(row['uncertainty_components_json'])
                require([x['source_component'] for x in details] == source['uncertainty']['components'], fmt, mid + ':all_independent_errors')
                require(all(x['measurement_id'] == mid for x in details), fmt, mid + ':error_binding')
                if len(details) != 1:
                    require(row['error_minus'] == row['error_plus'] == '', fmt, mid + ':no_error_merging')
                else:
                    component = (details[0].get('processed_component') if ready else None) or details[0]['source_component']
                    if component.get('interpretation_state') == 'parsed' and component['kind'] in {'symmetric_delta', 'asymmetric_delta'}:
                        values = component['values']
                        negative = values['delta'] if component['kind'] == 'symmetric_delta' else values['minus']
                        positive = values['delta'] if component['kind'] == 'symmetric_delta' else values['plus']
                        require(row['error_minus'] == (negative or '') and row['error_plus'] == (positive or ''), fmt, mid + ':error_sides')
                require(row['snapshot_id'] == body['snapshot_ref']['id'] and row['snapshot_sha256'] == body['snapshot_ref']['content_sha256'] and
                    row['delivery_revision'] == str(body['revision']) and row['selected_count'] == str(len(expected)), fmt, mid + ':revision')
        elif fmt == 'csv_wide':
            wide = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            actual = []
            for group in wide:
                for key, mid in group.items():
                    if not key.endswith(':measurement_id') or not mid:
                        continue
                    require(mid in expected, fmt, 'unknown_record')
                    pid = key[:-len(':measurement_id')]; actual.append(mid)
                    require(pid == expected[mid]['property_ref']['id'], fmt, mid + ':property')
                    for field in ('value', 'unit', 'error_minus', 'error_plus', 'error_unit', 'limit', 'raw_value', 'uncertainty_components_json'):
                        require(group[pid + ':' + field] == rows[mid][field], fmt, mid + ':' + field)
            require(len(actual) == len(expected) and set(actual) == set(expected), fmt, 'record_set')
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = json.loads(archive.read('manifest.json')); check_meta(manifest, fmt)
                require(archive.read('measurements.csv') == encoded['csv_long'] and
                    archive.read('delivery.json') == encoded['json'] and
                    archive.read('properties.json') == encoded['json_wide'], fmt, 'same_files')
                require(not manifest['original_files_included'], fmt, 'honest_original_inventory')
                for name, sha in manifest['files'].items():
                    require(hashlib.sha256(archive.read(name)).hexdigest() == sha, fmt, name)
        formats[fmt] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'media_type': media,
                        'source_records_verified': len(expected)}
    return {'schema_version': 'DeliverySerializationCheck/2', 'snapshot_ref': body['snapshot_ref'],
        'delivery_id': body['delivery_id'], 'state': 'passed', 'formats': formats, 'generator': 'research-export/2',
        'scope': 'Typed source/processed coordinates, separate original errors, selection, report revision and shared evidence.'}
