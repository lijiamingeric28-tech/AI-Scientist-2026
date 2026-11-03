import asyncio
import csv
import io
import pytest

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.science.catalog_transcription import preserve_catalog_fields
from astroquery_ai.science.extraction import MeasurementProposal
from astroquery_ai.science.catalogs import VizierCatalogs
from tests.rebuild.factories import measurement, ref


def proposal(errors=None):
    return MeasurementProposal.model_validate(
        {
            "property_id": "synthetic-column-density",
            "value": {"kind": "real", "value": "26.764100"},
            "raw_value": "26.764100",
            "unit": "pc.cm**-3",
            "representation": "linear",
            "source_quote": "SYNTHETIC table fixture",
            "page": None,
            "row": 0,
            "column": "DM",
            "subject_role": "target",
            "result_role": "reported_result",
            "location_kind": "catalog_cell",
            "limit": "none",
            "errors": errors or [],
            "conditions": [],
            "ambiguity": None,
        }
    )


def test_real_observed_failure_missing_error_value_remains_unresolved_not_lost():
    item = proposal(
        [
            {
                "location": "e_DM",
                "raw_text": "1e-04",
                "kind": "symmetric_delta",
                "values": None,
                "role": "unspecified",
                "meaning": "reported_error",
                "interpretation_state": "parsed",
                "reason": None,
            }
        ]
    )
    verified, checks = preserve_catalog_fields(
        item,
        {"DM": "26.764100", "e_DM": "1e-04", "r_DM": "SYNTHETIC-REF"},
        {"error_columns": ["e_DM"], "reference_columns": ["r_DM"]},
        [{"name": "e_DM"}],
    )
    assert verified.errors[0].raw_text == "1e-04"
    assert (
        verified.errors[0].interpretation_state == "unresolved"
        and verified.errors[0].values is None
    )
    assert verified.source_references[0].raw_code == "SYNTHETIC-REF"
    assert verified.conditions == [] and checks


def test_omitted_components_preserved_separately_and_source_null_not_zero():
    row = {"stat": "0", "sys": "0.002", "absent": "-999"}
    item, _ = preserve_catalog_fields(
        proposal(),
        row,
        {"error_columns": list(row), "reference_columns": []},
        [{"name": "absent", "null": "-999"}],
    )
    assert [(error.location, error.raw_text, error.role) for error in item.errors] == [
        ("stat", "0", "unspecified"),
        ("sys", "0.002", "unspecified"),
    ]
    assert all(error.interpretation_state == "unresolved" for error in item.errors)


def test_row_source_role_corrects_provisional_header_without_dropping_real_error():
    from astroquery_ai.science.extraction import CatalogFieldRole
    item = proposal().model_copy(update={'catalog_field_roles': [CatalogFieldRole(
        column='when', role='context', source_quote='Reference time of measurement',
        reason='Source explicitly gives a time coordinate, not an error amplitude.', context_key='reference_time')]})
    row = {'DM': '26.764100', 'when': '50000.000', 'err': '0.003'}
    mapping = {'error_columns': ['when', 'err']}
    columns = [{'name': 'when', 'description': 'Reference time of measurement in source days'},
               {'name': 'err', 'description': 'Reported measurement error'}]
    result, checks = preserve_catalog_fields(item, row, mapping, columns)
    assert [(e.location, e.raw_text) for e in result.errors] == [('err', '0.003')]
    assert result.conditions[0].value == '50000.000'
    assert any(c['state'] == 'source_evidenced_context_not_uncertainty' for c in checks)
    assert mapping['error_columns'] == ['when', 'err']
    fake = item.model_copy(update={'catalog_field_roles': [item.catalog_field_roles[0].model_copy(
        update={'source_quote': 'not in the actual source'})]})
    unchanged, _ = preserve_catalog_fields(fake, row, mapping, columns)
    assert {e.location for e in unchanged.errors} == {'when', 'err'}


def test_standalone_numeric_main_is_not_auto_added_as_its_own_error():
    result, checks = preserve_catalog_fields(proposal(), {'DM': '26.764100', 'err': '0.003'},
        {'value_column': 'DM', 'error_columns': ['DM', 'err']}, [])
    assert [(e.location, e.raw_text) for e in result.errors] == [('err', '0.003')]
    assert any(c['state'] == 'plain_numeric_main_not_its_own_uncertainty' for c in checks)


def test_readme_unknown_code_is_field_and_source_specific_not_a_global_zero_rule():
    item = proposal([{"location": "e_DM", "raw_text": "0.000", "kind": "symmetric_delta", "values": {"delta": "0"},
        "role": "unspecified", "meaning": "reported_error", "interpretation_state": "parsed", "reason": None}])
    item = item.model_copy(update={"value": item.value.model_copy(update={"value": "0"}), "raw_value": "0"})
    row = {"DM": "0", "e_DM": "0.000"}
    columns = [{"name": "DM", "unit_text": "pc.cm**-3"}, {"name": "e_DM", "unit_text": "pc.cm**-3"}]
    document = {"artifact_ref": ref("SYNTHETIC ReadMe"), "parsed": {"state": "table_layout_identified",
        "fields": {"e_DM": [{"text": "10-20 E10.3 pc.cm-3 e_DM ?=0 Mean error"}]}}}
    converted, _ = preserve_catalog_fields(item, row, {"value_column": "DM", "error_columns": ["e_DM"], "source_document": document}, columns)
    assert converted.raw_value == "0" and converted.value.value == "0"
    assert converted.errors[0].raw_text == "0.000" and converted.errors[0].values is None
    assert converted.errors[0].interpretation_state == "unresolved" and converted.errors[0].reason == "source_declared_unknown_code"
    other, _ = preserve_catalog_fields(item, row, {"value_column": "DM", "error_columns": ["e_DM"]}, columns)
    assert other.errors[0].interpretation_state == "parsed" and other.errors[0].values == {"delta": "0"}


def test_generic_uncertainty_does_not_establish_sigma_and_correlation_is_retained():
    item = proposal([{'location': 'err', 'raw_text': '0.053', 'kind': 'symmetric_delta',
        'values': {'delta': '0.053'}, 'role': 'total', 'meaning': 'standard_uncertainty',
        'interpretation_state': 'parsed', 'reason': 'Assumed by catalog convention',
        'catalog_semantics_evidence': [{'column': 'err', 'quote': 'Uncertainty (including systematic)', 'aspect': 'meaning'}]}])
    result, checks = preserve_catalog_fields(item, {'DM': '1.000', 'err': '0.053', 'rho': '0.019'},
        {'value_column': 'DM', 'error_columns': ['err'], 'context_columns': ['rho']},
        [{'name': 'err', 'description': 'Uncertainty (including systematic)'},
         {'name': 'rho', 'description': 'Correlation coefficient between uncertainties'}])
    assert result.errors[0].meaning == 'reported_error' and result.errors[0].role == 'unspecified'
    assert result.errors[0].values == {'delta': '0.053'}
    assert result.errors[1].kind == 'correlation' and result.errors[1].raw_text == '0.019'
    assert result.errors[1].interpretation_state == 'unresolved' and result.errors[1].values is None
    assert any(c['state'] == 'unsupported_error_semantics_not_promoted' for c in checks)


def test_literal_column_semantics_quote_can_support_declared_standard_error():
    item = proposal([{'location': 'err', 'raw_text': '0.01', 'kind': 'symmetric_delta',
        'values': {'delta': '0.01'}, 'role': 'unspecified', 'meaning': 'standard_uncertainty',
        'interpretation_state': 'parsed', 'reason': None,
        'catalog_semantics_evidence': [{'column': 'err', 'quote': 'Standard uncertainty', 'aspect': 'meaning'}]}])
    result, _ = preserve_catalog_fields(item, {'DM': '1.00', 'err': '0.01'},
        {'error_columns': ['err']}, [{'name': 'err', 'description': 'Standard uncertainty of the reported value'}])
    assert result.errors[0].meaning == 'standard_uncertainty'
    fabricated = item.model_copy(update={'errors': [item.errors[0].model_copy(update={
        'catalog_semantics_evidence': [item.errors[0].catalog_semantics_evidence[0].model_copy(update={'quote': 'one-sigma'})]})]})
    result, _ = preserve_catalog_fields(fabricated, {'DM': '1.00', 'err': '0.01'},
        {'error_columns': ['err']}, [{'name': 'err', 'description': 'Standard uncertainty of the reported value'}])
    assert result.errors[0].meaning == 'reported_error'


def test_omitted_header_mapping_does_not_drop_source_row_correlation_context():
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.science.catalog_transcription import reported_uncertainty_context
    source = {'source_id': 'test', 'metadata': {'columns': [
        {'name': 'rho', 'description': 'Correlation coefficient between uncertainties'},
        {'name': 'calibration', 'description': 'Calibration coefficient'}]}}
    doc = {'source_quote': canonical({'cells': {'rho': '0.000', 'calibration': '1.00'}}).decode(), 'row': 4}
    evidence = {'artifact_ref': ref('raw')}
    result = reported_uncertainty_context(source, doc, evidence, ref('evidence'))
    assert len(result) == 1 and result[0]['reported_value'] == '0.000'
    assert result[0]['column'] == 'rho' and result[0]['row'] == 4
    assert result[0]['axis_binding_state'] == 'unresolved' and result[0]['eligible_for_comparison'] is False
    assert result[0]['reported_relation_kind'] == 'correlation'


@pytest.mark.parametrize('raw', ['26.764100±0.0001', '26.764100(10)'])
def test_omitted_composite_uncertainty_and_full_source_text_remain_unresolved(raw):
    original = proposal()
    retained, checks = preserve_catalog_fields(original, {'DM': raw},
        {'value_column': 'DM', 'error_columns': []}, [{'name': 'DM', 'datatype': 'char'}])
    assert retained.raw_value == raw and retained.value == original.value
    assert len(retained.errors) == 1
    error = retained.errors[0]
    assert error.raw_text == raw and error.interpretation_state == 'unresolved' and error.values is None
    assert error.source_unit is None and error.role == 'unspecified'
    assert original.errors == []
    assert any(c['state'] == 'composite_uncertainty_raw_preserved_unresolved' for c in checks)


def test_actual_source_units_and_text_tokens_override_model_reformatting():
    item = proposal().model_copy(update={'unit': 'mJy'})
    retained, checks = preserve_catalog_fields(item, {'DM': '26.764100'},
        {'value_column': 'DM', 'error_columns': []}, [{'name': 'DM', 'unit_text': 'Jy'}])
    assert retained.unit == 'Jy' and retained.value == item.value
    assert any(c['state'] == 'source_unit_restored_from_actual_metadata' for c in checks)
    text = MeasurementProposal.model_validate({**item.model_dump(), 'value': {'kind': 'text', 'value': 'HE'}})
    retained, _ = preserve_catalog_fields(text, {'DM': 'HE[fixture,refs]'},
        {'value_column': 'DM', 'error_columns': []}, [{'name': 'DM', 'unit_text': None}])
    assert retained.value.value == retained.raw_value == 'HE[fixture,refs]'
    assert retained.unit is None and not retained.errors


def test_reference_codes_survive_standalone_long_and_wide_csv():
    record = measurement()
    record["lineage_refs"] = [ref("reported-source-test")]
    reported = {
        "reference_id": "reported-source-test",
        "raw_code": "SYNTHETIC-REF",
        "location": "r_value",
        "resolved_work_ref": None,
    }
    body = {
        "delivery_id": "synthetic-delivery",
        "measurements": [record],
        "derived": [],
        "contexts": [],
        "provenance_bundle": {"reported_references": [reported],
            'result_relationships': [{'kind': 'same_author_reported_result', 'measurement_ids': [record['measurement_id'], 'SYNTHETIC other mention']}],
            'source_mentions': [{'measurement_id': record['measurement_id'], 'source_quotes': ['SYNTHETIC original repeated statement']}]},
    }
    long, _ = DeliveryService._serialize(body, "csv_long")
    long_row = next(csv.DictReader(io.StringIO(long.decode("utf-8-sig"))))
    assert loads(long_row["source_references_json"]) == [{**reported,'cited_work':None}]
    assert loads(long_row['result_relationships_json']) == body['provenance_bundle']['result_relationships']
    assert loads(long_row['source_mentions_json']) == body['provenance_bundle']['source_mentions']
    wide, _ = DeliveryService._serialize(body, "csv_wide")
    wide_row = next(csv.DictReader(io.StringIO(wide.decode("utf-8-sig"))))
    assert loads(wide_row["synthetic-property"])[0]["reported_references"] == [{**reported,'cited_work':None}]
    assert loads(wide_row['result_relationships_json']) == body['provenance_bundle']['result_relationships']
    assert loads(wide_row['source_mentions_json']) == body['provenance_bundle']['source_mentions']


def test_vizier_strict_character_and_numeric_selector_have_no_quoted_literal():
    requests = []

    class HTTP:
        async def request(self, *args, **kwargs):
            requests.append(kwargs["params"])
            return b"<VOTABLE/>", {}

    async def run():
        catalogs = VizierCatalogs(HTTP())
        await catalogs.exact_query("synthetic", "SYNTHETIC/T", "Name", "B0329+54")
        await catalogs.exact_query(
            "synthetic", "SYNTHETIC/T", "Source", "1234567890123456789", datatype="long"
        )

    asyncio.run(run())
    data_requests=[r for r in requests if r.get('-source')=='SYNTHETIC/T']
    assert len(data_requests)==2
    assert data_requests[0]["Name"] == "==B0329+54"
    assert data_requests[1]["Source"] == "=1234567890123456789"
    assert all("-out.form" not in request for request in requests)
