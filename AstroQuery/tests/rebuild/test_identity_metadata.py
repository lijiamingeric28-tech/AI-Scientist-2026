from copy import deepcopy

import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.catalogs import (
    exact_identifier, exact_rows, local_identifier, declared_namespace, identifier_selectors, parse_votable,
)
from astroquery_ai.science.catalog_plan import compatible_returned_plan
from astroquery_ai.science.table_metadata import coordinate_groups
from astroquery_ai.science.identity_consistency import row_identifier_conflicts
from astroquery_ai.science.identity_binding import exact_binding
from astroquery_ai.science.identity_query import identifier_query
from tests.rebuild.scenario import application, confirmed_case
import asyncio
import httpx


def test_two_mass_prefix_is_catalog_specific_and_component_suffix_survives():
    column = {'name': '2MASS', 'datatype': 'char', 'description': '(designation) Source designation (1)', 'ucd': 'meta.id;meta.main'}
    namespace = declared_namespace(column, None)
    alias = '2MASS J17574849+0441405A'
    assert namespace == '2MASS' and local_identifier(alias, namespace) == '17574849+0441405A'
    assert identifier_selectors(alias, namespace) == ['17574849+0441405A', 'J17574849+0441405A', alias]
    assert exact_rows([{'2MASS': '17574849+0441405A'}, {'2MASS': '17574849+0441405'},
                       {'2MASS': '17574849+0441405B'}], ['2MASS'], [alias], {'2MASS': namespace}) == [0]
    assert exact_identifier(alias) != exact_identifier('2MASX J17574849+0441405A')
    assert local_identifier('Other J17574849+0441405A', namespace) is None


def test_gaia_native_release_requires_concrete_table_and_does_not_override_dr2():
    column = {'name': 'Source', 'datatype': 'long', 'description': 'Unique source identifier within one release', 'ucd': 'meta.id;meta.main'}
    table = {'table_id': 'I/355/gaiadr3', 'description': 'Gaia DR3 source catalog'}
    assert declared_namespace(column, None, table_metadata=table) == 'Gaia DR3'
    assert declared_namespace(column, 'Gaia DR3', table_metadata=table) == 'Gaia DR3'
    with pytest.raises(DomainError):
        declared_namespace({**column, 'description': 'Gaia DR2 source identifier'}, 'Gaia DR3', table_metadata=table)
    with pytest.raises(DomainError):
        declared_namespace({**column, 'ucd': 'meta.id.cross'}, 'Gaia DR3', table_metadata=table)
    with pytest.raises(DomainError):
        declared_namespace(column, 'Gaia DR3', table_metadata={**table, 'description': 'Gaia DR2 source catalog'})
    assert declared_namespace(column, None) is None
    designation = {'name': 'DR3Name', 'datatype': 'char', 'ucd': 'meta.id',
        'description': 'Unique source designation (unique across all Data Releases) (designation)'}
    assert declared_namespace(designation, None, table_metadata=table) == 'Gaia DR3'
    assert identifier_selectors('Gaia DR3 1234567890123456789', 'Gaia DR3', designation) == ['Gaia DR3 1234567890123456789']
    assert identifier_selectors('Gaia DR3 1234567890123456789', 'Gaia DR3', column) == ['1234567890123456789']
    with pytest.raises(DomainError):
        declared_namespace(designation, 'Gaia DR2', table_metadata=table)
    concrete = {**table, 'columns': [designation, column]}
    query = identifier_query(concrete, 'DR3Name', 'Gaia DR3', 'Gaia DR3 1234567890123456789')
    assert query['query_column'] == 'Source' and query['selector'] == '1234567890123456789'
    assert query['matched_returned_column_required'] == 'DR3Name'
    multiple = {**concrete, 'columns': [*concrete['columns'], {**column, 'name': 'AnotherNativeKey'}]}
    assert identifier_query(multiple, 'DR3Name', 'Gaia DR3', 'Gaia DR3 123')['query_column'] == 'DR3Name'


def table_xml(ref='native', epoch='J2016.0'):
    return f'''<VOTABLE><COOSYS ID="{ref}" system="ICRS" epoch="{epoch}"/>
    <TIMESYS ID="clock" timescale="UNKNOWN" refposition="UNKNOWN" timeorigin="0"/>
    <RESOURCE name="SYNTHETIC"><TABLE name="SYNTHETIC/table">
    <FIELD name="Name" datatype="char" arraysize="*"/>
    <FIELD name="RA" datatype="double" unit="deg" ref="{ref}" ucd="pos.eq.ra;meta.main"/>
    <FIELD name="DE" datatype="double" unit="deg" ref="{ref}" ucd="pos.eq.dec;meta.main"/>
    <FIELD name="JD" datatype="double" unit="d" ref="clock" ucd="time.epoch;obs"/>
    <DATA><TABLEDATA><TR><TD>SYNTHETIC</TD><TD>0</TD><TD>0</TD><TD>2451545.0</TD></TR></TABLEDATA></DATA>
    </TABLE></RESOURCE></VOTABLE>'''.encode()


def test_coordinate_time_definitions_and_zero_are_preserved_without_epoch_guess():
    parsed = parse_votable(table_xml())
    table = parsed['resources'][0]['tables'][0]
    assert table['rows'][0]['RA'] == table['rows'][0]['DE'] == '0'
    context = coordinate_groups(table)
    assert context['coordinate_groups'][0]['reference_epoch'] == 'J2016.0'
    assert context['time_columns'][0]['reference_context']['attributes']['timescale'] == 'UNKNOWN'
    assert not context['positional_acceptance_granted'] and not context['equinox_used_as_observation_time']
    no_epoch = table_xml().replace(b'epoch="J2016.0"', b'equinox="J2000"')
    context = coordinate_groups(parse_votable(no_epoch)['resources'][0]['tables'][0])
    assert context['coordinate_groups'][0]['reference_epoch'] is None
    assert context['coordinate_groups'][0]['equinox'] == 'J2000'


def test_response_local_ref_rename_is_equivalent_but_actual_epoch_change_is_not():
    original = parse_votable(table_xml())['resources'][0]['tables'][0]
    renamed = parse_votable(table_xml('renamed'))['resources'][0]['tables'][0]
    changed = parse_votable(table_xml('native', 'J2000'))['resources'][0]['tables'][0]
    plan = {'id_column': 'Name', 'identity_namespace': None, 'properties': [
        {'property_id': 'SYNTHETIC-ra', 'value_column': 'RA', 'error_columns': [], 'source_unit': 'deg', 'source_representation': 'linear'}]}
    kept, gaps = compatible_returned_plan(plan, original['columns'], renamed['columns'])
    assert len(kept['properties']) == 1 and not gaps
    kept, gaps = compatible_returned_plan(plan, original['columns'], changed['columns'])
    assert not kept['properties'] and gaps[0]['columns'][0]['changed_fields'] == ['reference_context']


def test_duplicate_reference_definitions_are_ambiguous_and_missing_ones_stay_unresolved():
    duplicate = table_xml().replace(b'<RESOURCE', b'<COOSYS ID="native" system="ICRS" epoch="J2000"/><RESOURCE', 1)
    table = parse_votable(duplicate)['resources'][0]['tables'][0]
    assert table['columns'][1]['reference_context']['state'] == 'ambiguous_reference'
    missing = table_xml().replace(b'ref="native"', b'ref="absent"')
    table = parse_votable(missing)['resources'][0]['tables'][0]
    assert table['columns'][1]['reference_context']['state'] == 'unresolved_reference'


def test_one_matching_key_cannot_hide_another_declared_conflicting_identity():
    table = {'table_id': 'I/355/gaiadr3', 'description': 'Gaia DR3 source catalog', 'columns': [
        {'name': 'Source', 'datatype': 'long', 'description': 'Unique source identifier within release', 'ucd': 'meta.id;meta.main'},
        {'name': '2MASS', 'datatype': 'char', 'description': 'Source designation', 'ucd': 'meta.id.cross'}]}
    target = {'target_id': 'SYNTHETIC', 'main_id': 'Gaia DR3 1234', 'aliases': ['2MASS J17574849+0441405A']}
    row = {'Source': '1234', '2MASS': '17574849+0441405B'}
    assert exact_rows([row], ['Source'], target['aliases'] + [target['main_id']], {'Source': 'Gaia DR3'}) == [0]
    conflicts = row_identifier_conflicts(target, table, row)
    assert len(conflicts) == 1 and conflicts[0]['column'] == '2MASS'
    with pytest.raises(DomainError, match='标识存在身份冲突'):
        exact_binding(target, table, [row], [0], 'Source', 'Gaia DR3', {'artifact_id': 'SYNTHETIC', 'sha256': 'SYNTHETIC'})
    assert not row_identifier_conflicts(target, table, {**row, '2MASS': ''})
    assert not row_identifier_conflicts(target, table, {**row, '2MASS': '17574849+0441405A'})


def test_production_catalog_measurement_points_to_its_exact_identity_binding(tmp_path):
    async def run():
        app = application(tmp_path)
        state, _ = await confirmed_case(app)
        tid = state['task_id']
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, tid)
            measurement = delivery['measurements'][0]
            evidence = next(e for e in delivery['evidence_index'] if e['evidence_id'] == measurement['evidence_refs'][0]['id'])
            ref = evidence['object_binding_ref']
            binding = app.repository.object(conn, tid, 'object_match', ref['id'], ref['version'])
            assert binding in delivery['provenance_bundle']['object_matches']
            assert binding['source_artifact_ref'] == evidence['artifact_ref']
            assert evidence['locator']['row'] in binding['source_rows']
            assert binding['actual_returned_keys'][0]['matched_target_alias'] == 'SYNTHETIC_AQ'
            assert binding['measurement_subject_validation_required'] is True
            interpretation = app.repository.object(conn, tid, 'interpretation', measurement['interpretation_ref']['id'])
            source = app.repository.object(conn, tid, 'source', measurement['source_ref']['id'])
            spec = app.repository.object(conn, tid, 'confirmed_query', delivery['query_ref']['id'], delivery['query_ref']['version'])
        bad = deepcopy(binding)
        bad['source_rows'] = [999]
        with app.repository.transaction() as conn:
            bad_ref = app.repository.put_object(conn, tid, 'object_match', 'SYNTHETIC wrong row', 1, bad)
        from astroquery_ai.science.extraction import EvidenceExtractor, MeasurementProposal
        artifact = app.artifacts.read_owned(tid, evidence['artifact_ref']['id'])[0]
        with pytest.raises(DomainError, match='匹配凭据不属于'):
            EvidenceExtractor(app).assemble(spec=spec,
                source=source, artifact=artifact, proposal=MeasurementProposal.model_validate(interpretation['proposal']),
                owner='M03', batch_id='SYNTHETIC wrong row', allowed_pages=[], matched_rows=[interpretation['proposal']['row']], object_binding_ref=bad_ref)
    asyncio.run(run())


def test_conflicting_returned_native_key_never_reaches_row_extraction(tmp_path):
    from tests.rebuild.test_new_end_to_end import SyntheticIdentity, XML_HEADER
    from tests.rebuild.scenario import ScenarioModels

    async def run():
        app = application(tmp_path)
        class Identity(SyntheticIdentity):
            async def resolve(self, task_id, mention):
                response = await super().resolve(task_id, mention)
                response['targets'][0]['aliases'].append('Gaia DR3 1234')
                return response
        class Models(ScenarioModels):
            row_calls = 0
            async def json(self, **kwargs):
                if kwargs['owner'] == 'M03' and kwargs['profile'].operation == 'catalog_rows':
                    self.row_calls += 1
                return await super().json(**kwargs)
        app.identity, app.models = Identity(app), Models()
        ordinary = app.http.transport
        header = XML_HEADER.replace(b'<FIELD name="Name"', b'<DESCRIPTION>Gaia DR3 source catalog SYNTHETIC</DESCRIPTION><FIELD name="Name"', 1)
        header += b'<FIELD name="Source" datatype="long" ucd="meta.id;meta.main"><DESCRIPTION>Unique source identifier within release</DESCRIPTION></FIELD>'
        async def http(request):
            if request.url.host in {'vizier.cds.unistra.fr', 'vizier.cfa.harvard.edu', 'vizier.idia.ac.za'}:
                data = b'<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0</TD><TD>5678</TD></TR></TABLEDATA></DATA>' if 'Name' in request.url.params else b''
                return httpx.Response(200, content=header + data + b'</TABLE></RESOURCE></VOTABLE>')
            return await ordinary.handle_async_request(request)
        app.http.transport = httpx.MockTransport(http)
        final, _ = await confirmed_case(app)
        assert app.models.row_calls == 0
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, final['task_id'])
        assert delivery['measurements'] == []
        queries = delivery['provenance_bundle']['catalog_identity_queries']
        assert queries and all(q['state'] == 'ambiguous_identity' for q in queries)
        assert all(q['identity_conflicts'][0]['rows']['0'][0]['actual_returned_key'] == '5678' for q in queries)
    asyncio.run(run())
