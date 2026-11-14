"""Research export contracts: useful columns without inventing scientific data."""
import csv
import io
import json
import unittest
import zipfile
from copy import deepcopy

from astroquery_ai.science.results.exporting import _serialize


def fixture():
    binding = {'property_id': 'p-temperature', 'definition': {
        'name_cn': '有效温度', 'definition_version': 1, 'content_sha256': 'a' * 64},
        'output_profile': {'unit': {'canonical_symbol': 'K'}, 'representation': {'kind': 'linear'}}}
    record = {'measurement_id': 'm1', 'property_ref': {'id': 'p-temperature'},
        'value': {'kind': 'real', 'value': '9620'}, 'raw_value': '9620 +61/-56 K',
        'representation': 'linear', 'limit': 'none', 'unit': 'K',
        'source_kind': 'paper', 'source_ref': {'id': 's1'},
        'evidence_refs': [{'id': 'e1'}], 'interpretation_ref': {'id': 'i1'},
        'uncertainty': {'state': 'reported', 'components': [{
            'component_id': 'c1', 'kind': 'asymmetric_delta', 'interpretation_state': 'parsed',
            'values': {'minus': '56', 'plus': '61'}, 'role': 'unspecified', 'level': None,
            'unit_ref': {'id': 'u1'}, 'raw_text': '+61/-56'}]}}
    second = deepcopy(record)
    second.update(measurement_id='m2', raw_value='9620 +49/-63 K')
    second['uncertainty']['components'][0].update(component_id='c2', values={'minus': '63', 'plus': '49'})
    return {'task_id': 'task', 'delivery_id': 'delivery', 'revision': 2,
        'snapshot_ref': {'id': 'science', 'content_sha256': 'b' * 64},
        'target': {'main_id': 'target'}, 'measurements': [record, second], 'derived': [],
        'definitions': [binding], 'sources': [{'source_id': 's1', 'title': ['Example'],
            'artifact': {'artifact_id': 'pdf1'}}],
        'contexts': [], 'evidence_index': [{'evidence_id': 'e1', 'source_id': 's1',
            'kind': 'paper', 'artifact_ref': {'id': 'pdf1'},
            'locator': {'page': 10}, 'raw_text': 'source text' * 50000}],
        'provenance_bundle': {'unit_records': [{'unit_id': 'u1', 'unit_text': 'K'}]},
        'export_selection': {'selected_ids': ['m1', 'm2']},
        'export_metadata': {'origin': 'http://127.0.0.1:8781'}}


def decode_csv(body, fmt='csv_long'):
    return list(csv.DictReader(io.StringIO(_serialize(body, fmt, export_schema_version=2)[0].decode('utf-8-sig'))))


class ResearchExports(unittest.TestCase):
    def test_asymmetric_versions_keep_sides_and_sortable_coordinate(self):
        b = fixture(); before = deepcopy(b)
        rows = decode_csv(b)
        self.assertEqual([(r['value'], r['error_minus'], r['error_plus']) for r in rows],
                         [('9620', '56', '61'), ('9620', '63', '49')])
        self.assertEqual(rows[0]['confidence_level'], '')
        self.assertEqual(rows[0]['original_url'], 'http://127.0.0.1:8781/api/tasks/task/artifacts/pdf1#page=10')
        self.assertLess(len(_serialize(b, 'csv_long', export_schema_version=2)[0]), 12000)
        self.assertEqual(b, before)

    def test_missing_and_independent_components_are_not_zero_or_averaged(self):
        b = fixture()
        b['measurements'][0]['uncertainty'] = {'state': 'not_reported', 'components': []}
        parts = b['measurements'][1]['uncertainty']['components']
        parts.append({**deepcopy(parts[0]), 'component_id': 'c3', 'role': 'systematic'})
        rows = decode_csv(b)
        self.assertTrue(all(r['error_minus'] == r['error_plus'] == '' for r in rows))
        self.assertEqual(rows[0]['uncertainty_state'], 'not_reported')
        self.assertEqual(len(json.loads(rows[1]['uncertainty_components_json'])), 2)

    def test_source_percent_error_is_not_labelled_as_processed_physical_unit(self):
        b = fixture(); b['provenance_bundle']['unit_records'][0]['unit_text'] = '%'
        b['derived'] = [{'measurement_id': 'm1', 'main_state': 'ready', 'status': 'ready',
            'value_typed': {'kind': 'real', 'value': '9.620'},
            'coordinate_units': {'target': 'kK'}, 'uncertainty_typed': {'components': []}}]
        row = decode_csv(b)[0]
        self.assertEqual((row['value'], row['unit'], row['error_unit']), ('9.620', 'kK', '%'))
        self.assertEqual(json.loads(row['uncertainty_components_json'])[0]['source_unit'], '%')

    def test_not_run_output_with_no_typed_error_keeps_source_error(self):
        b = fixture()
        b['derived'] = [{'measurement_id': 'm1', 'main_state': 'not_run', 'status': 'not_run',
            'value_typed': None, 'uncertainty_typed': None}]
        row = decode_csv(b)[0]
        self.assertEqual((row['value_origin'], row['value'], row['error_minus'], row['error_plus']),
                         ('source', '9620', '56', '61'))

    def test_dimensionless_coordinate_keeps_null_source_unit_in_json(self):
        from astroquery_ai.science.results.export_validation import verify_formats
        b = fixture(); b['measurements'][0]['unit'] = None
        self.assertEqual(decode_csv(b)[0]['source_unit'], '')
        self.assertIsNone(json.loads(_serialize(b, 'json', export_schema_version=2)[0])['measurements'][0]['unit'])
        self.assertEqual(verify_formats(b, export_schema_version=2)['state'], 'passed')

    def test_intervals_text_categories_and_formula_safety(self):
        b = fixture()
        b['measurements'][0].update(value={'kind': 'interval', 'lower': '1', 'upper': '2', 'lower_closed': False, 'upper_closed': True}, limit='interval')
        b['measurements'][1].update(value={'kind': 'category', 'code': 'A', 'raw_label': 'A star'}, raw_value='=cmd()')
        rows = decode_csv(b)
        self.assertEqual((rows[0]['value'], rows[0]['lower_bound'], rows[0]['upper_bound'], rows[0]['lower_closed']), ('', '1', '2', 'False'))
        self.assertEqual(rows[1]['text_value'], 'A star')
        self.assertEqual(rows[1]['raw_value'], "'=cmd()")
        full = json.loads(_serialize(b, 'json', export_schema_version=2)[0])
        self.assertEqual(full['measurements'][1]['raw_value'], '=cmd()')

    def test_same_paper_does_not_create_an_observation_group(self):
        b = fixture()
        b['definitions'].append({**deepcopy(b['definitions'][0]), 'property_id': 'p-gravity'})
        b['measurements'][1]['property_ref']['id'] = 'p-gravity'
        rows = decode_csv(b, 'csv_wide')
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['group_basis'] == 'unpaired_record' for r in rows))
        self.assertEqual(sum(bool(r['p-temperature:measurement_id']) for r in rows), 1)
        self.assertEqual(sum(bool(r['p-gravity:measurement_id']) for r in rows), 1)

    def test_evidenced_common_fit_can_pair_distinct_properties(self):
        b = fixture()
        b['definitions'].append({**deepcopy(b['definitions'][0]), 'property_id': 'p-gravity'})
        b['measurements'][1]['property_ref']['id'] = 'p-gravity'
        b['joint_measurement_groups'] = [{'group_id': 'fit1', 'basis': 'same_model_fit',
            'measurement_ids': ['m1', 'm2'], 'evidence_refs': [{'id': 'e1'}]}]
        rows = decode_csv(b, 'csv_wide')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['p-temperature:measurement_id'], rows[0]['p-gravity:measurement_id']), ('m1', 'm2'))

    def test_unavailable_group_evidence_never_pairs_records(self):
        b = fixture()
        b['joint_measurement_groups'] = [{'group_id': 'bad', 'basis': 'same_observation',
            'measurement_ids': ['m1', 'm2'], 'evidence_refs': [{'id': 'not-in-snapshot'}]}]
        self.assertEqual(len(decode_csv(b, 'csv_wide')), 2)

    def test_publication_verifier_checks_values_and_error_sides(self):
        from astroquery_ai.science.results import export_validation
        from astroquery_ai.runtime.errors import DomainError
        from unittest.mock import patch
        b = fixture()
        self.assertEqual(export_validation.verify_formats(b, export_schema_version=2)['state'], 'passed')
        original = export_validation._serialize
        def wrong_error(body, fmt, **kwargs):
            raw, media = original(body, fmt, **kwargs)
            if fmt == 'csv_long':
                rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
                rows[0]['error_plus'] = '56'
                stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, list(rows[0]))
                writer.writeheader(); writer.writerows(rows); raw = stream.getvalue().encode('utf-8-sig')
            return raw, media
        with patch.object(export_validation, '_serialize', wrong_error):
            with self.assertRaises(DomainError) as caught:
                export_validation.verify_formats(b, export_schema_version=2)
            self.assertEqual(caught.exception.code, 'EXPORT_CONTENT_MISMATCH')

    def test_json_properties_and_package_share_selection_and_one_large_evidence(self):
        b = fixture()
        grouped = json.loads(_serialize(b, 'json_wide', export_schema_version=2)[0])
        self.assertNotIn('metadata', grouped)
        self.assertEqual(grouped['properties'][0]['name'], '有效温度')
        self.assertEqual([r['source']['measurement_id'] for r in grouped['properties'][0]['records']], ['m1', 'm2'])
        raw, _ = _serialize(b, 'package', export_schema_version=2)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['selected_ids'], ['m1', 'm2'])
            self.assertFalse(manifest['original_files_included'])
            self.assertIn('column-dictionary.json', archive.namelist())
            self.assertIn('sources.json', archive.namelist())
            self.assertIn('errors.json', archive.namelist())
            self.assertNotIn('evidence_index', archive.read('measurements.csv').decode('utf-8-sig'))
            self.assertIn('包内没有原PDF', archive.read('README.md').decode())
            import hashlib
            for name, value in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), value)
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
        self.assertEqual(raw, _serialize(b, 'package', export_schema_version=2)[0])


def test_export_service_preserves_filtered_selection_retries_versions_and_snapshot(tmp_path):
    from uuid import uuid4
    import pytest
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.storage import ArtifactStore
    from astroquery_ai.runtime.delivery import DeliveryService
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.runtime.errors import DomainError
    repo = Repository(tmp_path / 'runtime.sqlite3')
    store = ArtifactStore(tmp_path / 'artifacts', repo)
    service = DeliveryService(repo, store)
    tid = repo.create_task('SYNTHETIC versioned export API fixture')['task_id']
    body = fixture(); body['task_id'] = tid
    with repo.transaction() as c:
        ref = repo.put_object(c, tid, 'delivery', body['delivery_id'], body['revision'], body)
        repo.mutate_task(c, tid, lifecycle='completed', science_state='sealed', delivery_ref=canonical(ref).decode())
    for fmt in ('csv_long', 'csv_wide', 'json', 'json_wide', 'package'):
        request = {'operation_id': str(uuid4()), 'task_id': tid, 'delivery_id': body['delivery_id'],
            'expected_delivery_revision': 2, 'selection': {'mode': 'ids', 'measurement_ids': ['m2']},
            'format': fmt, 'export_schema_version': 2}
        result = service.export(tid, request, origin='http://localhost:8781/')
        assert result['selection']['selected_ids'] == ['m2'] and result['selected_count'] == 1
        assert result['snapshot_ref'] == body['snapshot_ref'] and result['delivery_revision'] == 2
        assert service.export(tid, request, origin='http://localhost:8781/') == result
        again = service.export(tid, {**request, 'operation_id': str(uuid4())}, origin='http://localhost:8781/')
        assert again['export_id'] == result['export_id'] and again['artifacts'] == result['artifacts']
        raw = store.path(result['artifacts'][0]['relative_path']).read_bytes()
        if fmt == 'json':
            assert [m['measurement_id'] for m in json.loads(raw)['measurements']] == ['m2']
        if fmt == 'csv_long':
            row = next(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            assert row['error_minus'] == '63' and row['error_plus'] == '49'
            assert row['original_url'].startswith('http://localhost:8781/api/tasks/' + tid)
    old = service.export(tid, {**request, 'operation_id': str(uuid4()), 'format': 'json', 'export_schema_version': 1})
    assert old['schema_version'] == 'ExportManifest/1'
    with pytest.raises(DomainError) as error:
        service.export(tid, {**request, 'operation_id': str(uuid4()), 'expected_delivery_revision': 1})
    assert error.value.code == 'DELIVERY_CHANGED'
    with repo.read() as c:
        assert service.get(c, tid) == body
        assert c.execute('select count(*) from attempts').fetchone()[0] == 0


if __name__ == '__main__':
    unittest.main()
