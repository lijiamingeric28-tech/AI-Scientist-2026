import asyncio

from astroquery_ai.science.catalog_plan import validate_plan, compatible_returned_plan
from tests.rebuild.scenario import application, confirmed_case, ScenarioModels


def test_bad_mapping_does_not_discard_independent_valid_column_group():
    good = {
        "property_id": "synthetic-length",
        "value_column": "Length",
        "error_columns": [],
        "source_unit": "m",
        "source_representation": "linear",
    }
    raw = {
        "id_column": "Name",
        "identity_namespace": None,
        "properties": [
            good,
            {**good, "error_columns": ["Nonexistent"]},
            {**good, "property_id": {"invalid": True}},
        ],
        "limitations": [],
    }
    plan, gaps = validate_plan(raw, {"Name", "Length"}, {"synthetic-length"})
    assert plan["properties"] == [good]
    assert [item["reason"] for item in gaps] == [
        "linked_column_not_available",
        "property_or_column_not_authorized",
    ]
    assert len(raw["properties"]) == 3  # input/model receipt remains unchanged


def test_null_optional_placeholders_do_not_erase_real_value_mapping():
    mapping = {'property_id': 'synthetic-length', 'value_column': 'Length', 'error_columns': [None],
               'context_columns': [None], 'source_unit': 'm', 'source_representation': 'linear'}
    raw = {'id_column': 'Name', 'identity_namespace': None, 'properties': [mapping], 'limitations': []}
    plan, gaps = validate_plan(raw, {'Name', 'Length'}, {'synthetic-length'})
    assert plan['properties'][0]['value_column'] == 'Length'
    assert plan['properties'][0]['error_columns'] == []
    assert gaps[0]['state'] == 'protocol_normalized'
    assert mapping['error_columns'] == [None]
    # A real but unavailable linked field still fails normal validation.
    plan, gaps = validate_plan({**raw, 'properties': [{**mapping, 'error_columns': [None, 'NoSuchError']}]},
                               {'Name', 'Length'}, {'synthetic-length'})
    assert plan['properties'] == []
    assert gaps[-1]['reason'] == 'linked_column_not_available'


def test_real_observed_limitations_string_gets_one_repair_before_object_query(tmp_path):
    async def run():
        app = application(tmp_path)

        class Models(ScenarioModels):
            header_calls = 0

            async def json(self, *, owner, **kwargs):
                response, receipt = await super().json(owner=owner, **kwargs)
                if owner == "M03" and "id_column" in response:
                    self.header_calls += 1
                    if self.header_calls == 1:
                        response["limitations"] = (
                            "SYNTHETIC format defect observed in real calibration"
                        )
                return response, receipt

        app.models = Models()
        state, _ = await confirmed_case(app)
        assert state["lifecycle"] == "completed" and app.models.header_calls == 2
        with app.repository.read() as conn:
            assert len(app.repository.objects(conn, state["task_id"], "measurement")) == 1

    asyncio.run(run())


def test_actual_returned_unit_or_linked_error_change_quarantines_only_affected_group():
    columns = [{'name': 'Name', 'datatype': 'char'}, {'name': 'Length', 'unit_text': 'm'},
               {'name': 'e_Length', 'unit_text': 'm'}, {'name': 'Mass', 'unit_text': 'kg'}]
    plan = {'id_column': 'Name', 'properties': [
        {'property_id': 'length', 'value_column': 'Length', 'error_columns': ['e_Length']},
        {'property_id': 'mass', 'value_column': 'Mass', 'error_columns': []}]}
    changed = [{**c, 'unit_text': 'cm'} if c['name'] == 'e_Length' else dict(c) for c in columns]
    valid, gaps = compatible_returned_plan(plan, columns, changed)
    assert [m['property_id'] for m in valid['properties']] == ['mass']
    assert gaps[0]['columns'] == [{'column': 'e_Length', 'changed_fields': ['unit_text']}]
    assert len(plan['properties']) == 2
    changed[0]['description'] = 'SYNTHETIC host object, not the requested source'
    valid, gaps = compatible_returned_plan(plan, columns, changed)
    assert not valid['properties'] and gaps[0]['reason'] == 'identifier_schema_changed'
