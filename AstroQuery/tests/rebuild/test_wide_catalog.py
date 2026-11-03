"""Fresh wide-table integration, not a scientific accuracy fixture."""
import asyncio

import httpx
import pytest

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.scheduler import Scheduler
from astroquery_ai.runtime.throughput import DispatchDeferred
from astroquery_ai.science.workflow.catalog_service import CatalogService
from tests.rebuild.scenario import application, confirmed_case, run_until_wait, ScenarioModels


@pytest.mark.parametrize('array_source', [False, True])
@pytest.mark.parametrize('defer_row', [False, True])
def test_fitting_wide_header_keeps_far_error_without_forced_batches(tmp_path, array_source, defer_row):
    async def run():
        app = application(tmp_path)
        names = ['Name', *['SYNTHETIC_unused_' + str(i) for i in range(1, 64)], 'Length']
        names[31] = 'e_Length'
        fields = ''.join(f'<FIELD name="{name}" datatype="{"char" if name == "Name" else "double"}" unit="m"><DESCRIPTION>{"Synthetic whole length error" if name == "e_Length" else "Synthetic whole length" if name == "Length" else "SYNTHETIC unused test column"}</DESCRIPTION></FIELD>' for name in names)
        if array_source:
            fields = fields.replace('name="Length" datatype="double"', 'name="Length" datatype="double" arraysize="2"')
        prefix = ('<VOTABLE><RESOURCE name="J/SYNTHETIC/v1"><TABLE name="J/SYNTHETIC/v1/measurements">' + fields).encode()
        schema_calls = []

        def http(request):
            if request.url.host == 'api.adsabs.harvard.edu':
                return httpx.Response(200, json={'response': {'numFound': 0, 'docs': []}})
            if request.url.params.get('-source'):
                if request.url.params.get('-out.max') == '0' and request.url.params.get('-source')=='J/SYNTHETIC/v1/measurements':
                    schema_calls.append(request)
                if 'Name' in request.url.params:
                    cells = ['SYNTHETIC_AQ' if n == 'Name' else '12.30' if n == 'Length' else '.07' if n == 'e_Length' else '0' for n in names]
                    if array_source:
                        cells[-1] = '12.30 14.50'
                    data = ('<DATA><TABLEDATA><TR>' + ''.join('<TD>' + x + '</TD>' for x in cells) + '</TR></TABLEDATA></DATA>').encode()
                else:
                    data = b''
                return httpx.Response(200, content=prefix + data + b'</TABLE></RESOURCE></VOTABLE>')
            return httpx.Response(200, content=prefix + b'</TABLE></RESOURCE></VOTABLE>')

        app.http.transport = httpx.MockTransport(http)

        class Models(ScenarioModels):
            targets = []
            deferred = False

            async def json(self, *, owner, **kwargs):
                if owner != 'M03' or kwargs['profile'].operation == 'catalog_select':
                    return await super().json(owner=owner, **kwargs)
                prompt = loads(kwargs['messages'][-1]['content'])
                receipt = {'attempt_id': 'SYNTHETIC wide model', 'usage': None}
                if 'rows' in prompt:
                    if defer_row and not self.deferred:
                        self.deferred = True
                        raise DispatchDeferred('SYNTHETIC-row-slot', .05)
                    attr = prompt['table']['column_attributes']
                    supplied = {c[attr.index('name')] for c in prompt['table']['columns']}
                    # The row step may inspect real auxiliary columns while
                    # bounded, so a provisional header omission stays visible.
                    # Its invariant is complete required fields and no invented
                    # schema/cells, rather than an exact implementation subset.
                    assert {'Name', 'Length', 'e_Length'} <= supplied <= set(names)
                    assert set(prompt['rows'][0]['cells']) == supplied
                    return {'coverage': 'checked', 'limitations': [], 'results': [{
                        'property_id': 'synthetic-length', 'value': {'kind': 'real', 'value': '12.30'},
                        'raw_value': '12.30', 'unit': 'm', 'representation': 'linear',
                        'source_quote': 'SYNTHETIC exact source cells', 'page': None, 'row': 0,
                        'column': 'Length', 'subject_role': 'target', 'result_role': 'reported_result',
                        'location_kind': 'catalog_cell', 'limit': 'none', 'conditions': [], 'ambiguity': None,
                        'errors': [{'kind': 'symmetric_delta', 'values': {'delta': '.07'},
                            'raw_text': '.07', 'location': 'e_Length', 'source_unit': 'm',
                            'role': 'unspecified', 'meaning': 'reported_error',
                            'interpretation_state': 'parsed', 'reason': None}]}]}, receipt
                targets = prompt.get('target_columns', names)
                self.targets.append(targets)
                attributes = prompt['table']['column_attributes']
                supplied = {c[attributes.index('name')] for c in prompt['table']['columns']}
                assert supplied == set(names)  # Necessary error/ID metadata was not split away.
                properties = [{'property_id': 'synthetic-length', 'value_column': 'Length',
                    'error_columns': ['e_Length'], 'source_unit': 'm', 'source_representation': 'linear'}] if 'Length' in targets else []
                output = {'id_column': 'Name', 'identity_namespace': None, 'properties': properties, 'limitations': []}
                if 'target_columns' not in prompt:
                    return output, receipt
                return {**output, 'column_resolution': [{'column': n, 'role': 'value' if n == 'Length' else 'error' if n == 'e_Length' else 'identity' if n == 'Name' else 'not_relevant',
                        'reason': 'SYNTHETIC explicitly declared test role'} for n in targets]}, receipt

        app.models = Models()
        try:
            state, scheduler = await confirmed_case(app)
        except DispatchDeferred as wait:
            # The direct scenario driver doesn't run Scheduler's worker catch.
            # Exercise the same production deferral handler before reclaiming.
            scheduler = Scheduler(app)
            with app.repository.read() as conn:
                job = dict(conn.execute("SELECT * FROM jobs WHERE status='running'").fetchone())
            job['payload'] = loads(job['payload'])
            scheduler.fail(job, wait)
            state = app.view(job['task_id'])
        for _ in range(4):
            if state['lifecycle'] == 'completed':
                break
            await asyncio.sleep(.06)
            await run_until_wait(app, scheduler)
            state = app.view(state['task_id'])
        assert state['science_state'] == 'sealed' and state['lifecycle'] == 'completed'
        assert len(schema_calls) == 1
        assert list(map(len, app.models.targets)) == [65]
        assert {c for group in app.models.targets for c in group} == set(names)
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, state['task_id'])
            if array_source:
                assert delivery['measurements'] == []
                assert any(r['reason'] == 'source_array_or_complex_value_not_scalar' for r in delivery['dispositions'])
                return
            assert len(delivery['measurements']) == 1
            record = delivery['measurements'][0]
            assert record['raw_value'] == '12.30'
            assert record['uncertainty']['components'][0]['values']['delta'] == '.07'
            assert len(delivery['provenance_bundle']['catalog_column_plans']) == 1
            assert len(delivery['provenance_bundle']['catalog_schemas']) == 0
            assert len(delivery['provenance_bundle']['object_matches']) == 1

    asyncio.run(run())


def test_unresolved_fields_and_context_columns_do_not_grant_extra_value_columns():
    raw = {'id_column': 'Name', 'identity_namespace': None, 'limitations': [],
        'properties': [{'property_id': 'p', 'value_column': c, 'error_columns': [],
            'source_unit': 'm', 'source_representation': 'linear'} for c in ['Length', 'Outside']],
        'column_resolution': [{'column': 'Length', 'role': 'value', 'reason': 'SYNTHETIC explicit length'},
                              {'column': 'Missing', 'role': [], 'reason': 'bad model item'}]}
    plan, gaps, resolution = CatalogService.validate_column_plan(raw, {'Name', 'Length', 'Outside', 'Missing'}, {'p'}, ['Length', 'Missing'])
    assert [m['value_column'] for m in plan['properties']] == ['Length']
    assert resolution[1]['role'] == 'unresolved'
    assert {g['reason'] for g in gaps} >= {'value_column_outside_target_group', 'invalid_column_resolution', 'column_not_resolved_in_response'}
