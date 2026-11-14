import asyncio
import csv
import io
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from astroquery_ai.runtime.codec import loads
from tests.rebuild.registry_fixture import make_release
from tests.rebuild.scenario import application, confirmed_case, ScenarioModels


@pytest.mark.parametrize('has_declaration', [True, False])
@pytest.mark.parametrize('unit_token', ['---', '10-9'])
def test_blank_field_unit_requires_source_declaration_not_a_dimensionless_target(tmp_path, has_declaration, unit_token):
    async def run():
        make_release(tmp_path / 'synthetic-package', dimensionless=True)
        app = application(tmp_path)
        ordinary = app.http.transport
        header = b'''<VOTABLE><RESOURCE name="J/SYNTHETIC/v1"><TABLE name="J/SYNTHETIC/v1/measurements">
        <FIELD name="Name" datatype="char" arraysize="*"><DESCRIPTION>Full object identifier</DESCRIPTION></FIELD>
        <FIELD name="Length" datatype="double"><DESCRIPTION>SYNTHETIC reported dimensionless ratio</DESCRIPTION></FIELD>
        <FIELD name="e_Length" datatype="double" ucd="stat.error"><DESCRIPTION>SYNTHETIC reported error</DESCRIPTION></FIELD>'''
        async def http(request):
            if request.url.host in {'cdsarc.cds.unistra.fr', 'vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(200, text='''SYNTHETIC DOCUMENT
Byte-by-byte Description of file: measurements.dat
------------------------------------------------
 Bytes Format Units Label Explanations
------------------------------------------------
 1-20 A20 --- Name Full source identifier
 22-30 F9.3 --- Length SYNTHETIC reported dimensionless ratio
 32-40 F9.3 --- e_Length SYNTHETIC source error
------------------------------------------------
'''.replace('F9.3 ---', 'F9.3 ' + unit_token)) if has_declaration else httpx.Response(404)
            if request.url.host in {'vizier.cds.unistra.fr', 'vizier.idia.ac.za', 'vizier.cfa.harvard.edu'}:
                data = b'<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0.50</TD><TD>.03</TD></TR></TABLEDATA></DATA>' if 'Name' in request.url.params else b''
                return httpx.Response(200, content=header + data + b'</TABLE></RESOURCE></VOTABLE>')
            return await ordinary.handle_async_request(request)
        app.http.transport = httpx.MockTransport(http)
        class Models(ScenarioModels):
            async def json(self, **kwargs):
                response, receipt = await super().json(**kwargs)
                if kwargs['owner'] == 'M03' and kwargs['profile'].operation != 'catalog_select':
                    if 'rows' not in loads(kwargs['messages'][-1]['content']):
                        response['properties'][0].update(source_unit=None, error_columns=['e_Length'])
                    else:
                        p = response['results'][0]
                        p.update(unit=None, raw_value='0.50', value={'kind': 'real', 'value': '0.50'},
                            errors=[{'kind': 'symmetric_delta', 'values': {'delta': '.03'}, 'raw_text': '.03',
                                'source_unit': None, 'location': 'e_Length', 'interpretation_state': 'parsed',
                                'role': 'unspecified', 'meaning': 'reported_error', 'reason': None}])
                return response, receipt
        app.models = Models()
        final, _ = await confirmed_case(app)
        if not has_declaration:
            # A missing unit declaration is not a grounded scientific choice
            # with answerable alternatives; retain the candidate/coverage.
            assert final['lifecycle'] == 'completed' and not final['reviews']
            with app.repository.read() as conn:
                assert not app.repository.objects(conn,final['task_id'],'measurement')
                assert any(x.get('reason')=='source_unit_missing' for x in app.repository.objects(conn,final['task_id'],'coverage'))
            return
        assert final['lifecycle'] == 'completed'
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, final['task_id'])
        source = delivery['measurements'][0]
        declaration_kind = 'dimensionless' if unit_token == '---' else 'source_declared_unit'
        factor = Decimal(1) if unit_token == '---' else Decimal('1e-9')
        assert source['unit'] is None and source['unit_declaration']['kind'] == declaration_kind
        assert source['unit_declaration']['source_literal'] == unit_token
        assert source['uncertainty']['components'][0]['values']['delta'] == '.03'
        derived = delivery['derived'][0]
        assert derived['status'] == 'ready' and Decimal(derived['value_typed']['value']) == Decimal('0.50') * factor
        assert Decimal(derived['uncertainty_typed']['components'][0]['output_component']['values']['delta']) == Decimal('.03') * factor
        assert any(u.get('unit_text') is None and u.get('unit_declaration', {}).get('kind') == declaration_kind
                   for u in delivery['provenance_bundle']['unit_records'])
        for fmt in ['json', 'csv_long', 'json_wide', 'csv_wide', 'package']:
            exported = app.delivery.export(final['task_id'], {'operation_id': str(uuid4()),
                'task_id': final['task_id'], 'delivery_id': delivery['delivery_id'], 'expected_delivery_revision': 1,
                'selection': {'mode': 'all', 'measurement_ids': []}, 'format': fmt, 'export_schema_version': 1})
            _, path = app.artifacts.read_owned(final['task_id'], exported['artifacts'][0]['artifact_id'])
            if fmt == 'json':
                assert loads(path.read_bytes())['measurements'][0]['unit_declaration'] == source['unit_declaration']
            if fmt == 'csv_long':
                row = list(csv.DictReader(io.StringIO(path.read_text('utf-8-sig'))))[0]
                assert row['source_unit'] == ''
                assert loads(row['source_unit_declaration_json']) == source['unit_declaration']
                assert loads(row['source_measurement_json']) == source
    asyncio.run(run())
