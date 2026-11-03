from decimal import Decimal as D

import pytest

from astroquery_ai.registry.models import Representation
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import SourceMeasurement
from astroquery_ai.science.normalization import (
    SameQuantityTransform,
    normalize_checked,
    verify_model_numbers,
)
from astroquery_ai.science.quality import assess as assess_raw
from astroquery_ai.science.differences import compare
from tests.rebuild.factories import ref, error_component, measurement, derived


def assess(records, *args, **kwargs):
    # These scoring examples explicitly stipulate completed source checks.
    return assess_raw(
        records,
        *args,
        source_checks={r["measurement_id"]: {"state": "checked"} for r in records},
        **kwargs,
    )


def test_unchecked_source_is_unassessed_and_never_defaults_to_100():
    record = measurement()
    report = assess_raw(
        [record],
        [derived(record)],
        ["synthetic-property"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
    )
    assert report["overall_score"] is None
    assert report["measurements"][0]["delivery"] == 100
    assert report["measurements"][0]["adoption"] is None
    assert report["issues"][0]["rule_id"] == "source_restrictions_not_checked"


def test_equal_numeric_spelling_is_not_a_difference():
    records = [measurement("one", value="1.0"), measurement("two", value="1.00")]
    bindings = [
        {
            "property_id": "synthetic-property",
            "definition": {"measurement_conditions_schema": []},
            "output_profile": {"version": 1},
        }
    ]
    assert compare(records, list(map(derived, records)), [], bindings, ref())["groups"] == []


def test_component_unit_scaling_and_variance_dimension_are_preserved():
    component = error_component(values={"delta": "2"})
    record = measurement(components=[component])
    result = normalize_checked(
        SourceMeasurement.model_validate(record),
        transform(),
        ref("target-profile"),
        target_unit_ref=ref("target-unit"),
        target_representation_ref=ref("target-space"),
        component_units={component["unit_ref"]["id"]: "cm"},
    )
    assert D(
        result["uncertainty_typed"]["components"][0]["output_component"]["values"]["delta"]
    ) == D(2)
    variance = error_component(kind="variance", values={"delta": "0.04"})
    result = normalize(measurement(components=[variance]), transform())
    converted = result["uncertainty_typed"]["components"][0]
    assert converted["unit_definition"]["power"] == 2
    assert converted["unit_definition"]["canonical_symbol"] == "cm2"
    assert D(converted["output_component"]["values"]["delta"]) == D(400)


def transform(source=None, target=None, source_unit="m", target_unit="cm"):
    return SameQuantityTransform(
        source or Representation(kind="linear"),
        target or Representation(kind="linear"),
        source_unit,
        target_unit,
        source_quantity_key="SYNTHETIC:length",
        target_quantity_key="SYNTHETIC:length",
    )


def test_registered_unit_scales_preserve_exact_equivalent_units_without_rounding():
    from astroquery_ai.science.units import decimal_unit_factor
    assert decimal_unit_factor('1e-07W', 'erg.s-1') == D(1)
    assert decimal_unit_factor('10-9', '1') == D('1e-9')
    assert decimal_unit_factor('ms', 's') == D('.001')
    checked = transform(source_unit='1e-07W', target_unit='erg.s-1')
    value = D('3.166e34')
    assert checked.apply(value) == value


def test_dimensionless_percentage_profile_keeps_its_fixed_coefficient_encoding():
    from astroquery_ai.science.unit_declarations import output_coordinate_unit
    target = {'unit': {'kind': 'dimensionless', 'semantic_kind': 'polarization_percentage'}}
    unit = output_coordinate_unit(target)
    assert unit == '%'
    assert transform(source_unit='%', target_unit=unit).apply(D('92.4')) == D('92.4')
    assert transform(source_unit='1', target_unit=unit).apply(D('.924')) == D('92.4')
    assert transform(source_unit='%', target_unit=unit).apply(D('-6.2')) == D('-6.2')


def normalize(record, conversion):
    return normalize_checked(
        SourceMeasurement.model_validate(record),
        conversion,
        ref("target-profile"),
        target_unit_ref=ref("target-unit"),
        target_representation_ref=ref("target-space"),
    )


def test_log_error_uses_dex_coordinates_and_rejects_an_unrelated_physical_error_unit():
    component = error_component(values={'delta': '0.02'}, role='unspecified')
    source = measurement(value='2', components=[component])
    source['representation'], source['unit'] = 'log10', 'dex'
    conversion = transform(source=Representation(kind='log10', reference_value='1', reference_unit='m'),
                           source_unit='dex', target_unit='m')
    result = normalize_checked(SourceMeasurement.model_validate(source), conversion, ref('target-profile'),
        target_unit_ref=ref('target-unit'), target_representation_ref=ref('target-space'),
        component_units={component['unit_ref']['id']: 'dex'})
    converted = result['uncertainty_typed']['components'][0]
    assert result['status'] == 'ready' and converted['status'] == 'approximate'
    assert abs(D(converted['output_component']['values']['delta']) - D(100) * D(10).ln() * D('.02')) < D('1e-24')
    assert converted['output_component']['role'] == 'unspecified'
    assert source['uncertainty']['components'][0]['values'] == {'delta': '0.02'}
    invalid = normalize_checked(SourceMeasurement.model_validate(source), conversion, ref('target-profile'),
        target_unit_ref=ref('target-unit'), target_representation_ref=ref('target-space'),
        component_units={component['unit_ref']['id']: 'kg'})
    assert invalid['main_state'] == 'ready' and invalid['status'] == 'partial'
    assert invalid['uncertainty_typed']['components'][0]['output_component'] is None


def test_model_component_order_is_not_meaning_but_duplicate_ids_are_rejected():
    expected = {'value_typed': {'kind': 'real', 'value': '3'}, 'components': [
        {'source_component_id': 'stat', 'output_values': {'delta': '0.1'}},
        {'source_component_id': 'sys', 'output_values': {'delta': '0.4'}}]}
    reordered = {**expected, 'components': list(reversed(expected['components']))}
    verify_model_numbers(reordered, expected)
    with pytest.raises(DomainError, match='重复、缺失或越权'):
        verify_model_numbers({**expected, 'components': [expected['components'][0]] * 2}, expected)


def test_optional_unresolved_error_keeps_explicit_state_without_zero_fill():
    component = error_component()
    component.update(interpretation_state='unresolved', values=None, reason='SYNTHETIC basis missing')
    source = measurement(components=[component])
    source['uncertainty'].update(state='unresolved', reason='SYNTHETIC basis missing')
    result = normalize(source, transform())
    assert result['main_state'] == 'ready' and result['status'] == 'ready'
    assert result['uncertainty_typed']['state'] == 'source_unresolved'
    assert result['uncertainty_typed']['components'][0]['output_component'] is None
    assert source['uncertainty']['components'][0]['raw_text'] == component['raw_text']


def test_identity_preserves_long_decimal_and_extreme_log_underflow_is_failure():
    literal = "1." + "1234567890" * 12
    result = normalize(measurement(value=literal), transform(target_unit="m"))
    assert result["value_typed"]["value"] == literal
    record = measurement(value="-2000000")
    result = normalize(
        record,
        transform(
            source=Representation(kind="log10", reference_value="1", reference_unit="m"),
            target_unit="m",
        ),
    )
    assert result["status"] == "failed" and result["value_typed"] is None
    assert record["value"]["value"] == "-2000000"


def test_affine_delta_never_adds_offset_and_sides_stay_separate():
    c1 = error_component(values={"delta": "0.2"})
    c2 = error_component("sys", "asymmetric_delta", {"minus": None, "plus": "0.4"}, "sys")
    result = normalize(
        measurement(components=[c1, c2]),
        transform(target=Representation(kind="linear", offset="10")),
    )
    assert result["status"] == "ready"
    assert D(result["value_typed"]["value"]) == D(190)
    components = result["uncertainty_typed"]["components"]
    assert D(components[0]["output_component"]["values"]["delta"]) == D(20)
    assert components[1]["output_component"]["values"]["minus"] is None
    assert D(components[1]["output_component"]["values"]["plus"]) == D('40.00')
    assert components[1]["output_component"]["role"] == "sys"


def test_log_to_linear_small_error_is_approximate_large_error_is_partial():
    log = Representation(kind="log10", reference_value="1", reference_unit="m")
    conversion = transform(source=log, target_unit="m")
    small = normalize(measurement(components=[error_component()]), conversion)
    assert small["status"] == "ready"
    assert D(small["value_typed"]["value"]) == D(100)
    error = small["uncertainty_typed"]["components"][0]
    assert error["status"] == "approximate"
    assert abs(D(error["output_component"]["values"]["delta"]) - D("23.02585092994045684")) < D(
        "1e-15"
    )
    large = normalize(
        measurement(components=[error_component(values={"delta": "0.3"})]), conversion
    )
    assert large["main_state"] == "ready" and large["status"] == "partial"
    assert large["uncertainty_typed"]["components"][0]["output_component"] is None


def test_confidence_error_uses_endpoints_not_first_order():
    log = Representation(kind="log10", reference_value="1", reference_unit="m")
    record = measurement(
        components=[error_component(values={"delta": "0.3"}, meaning="confidence_interval")]
    )
    result = normalize(record, transform(source=log, target_unit="m"))
    component = result["uncertainty_typed"]["components"][0]
    assert component["method"] == "endpoint_mapping"
    assert component["output_component"]["kind"] == "interval_endpoints"
    assert D(component["output_component"]["values"]["lower"]) < D(51)
    assert component["output_component"]["level"] is None
    assert record["uncertainty"]["components"][0]["values"] == {"delta": "0.3"}


def test_decreasing_transform_swaps_sides_and_limit_direction():
    record = measurement(
        components=[
            error_component(kind="asymmetric_delta", values={"minus": "0.1", "plus": "0.3"})
        ]
    )
    record["limit"] = "upper"
    result = normalize(
        record, transform(target=Representation(kind="linear", scale="-1"), target_unit="m")
    )
    assert result["limit"] == "lower"
    values = result["uncertainty_typed"]["components"][0]["output_component"]["values"]
    assert D(values["minus"]) == D("0.3") and D(values["plus"]) == D("0.1")


def test_interval_main_value_does_not_create_a_midpoint():
    record = measurement()
    record["value"] = {
        "kind": "interval",
        "lower": "1",
        "upper": "3",
        "lower_closed": False,
        "upper_closed": True,
    }
    result = normalize(record, transform())
    assert {**result["value_typed"], 'lower': str(D(result['value_typed']['lower'])), 'upper': str(D(result['value_typed']['upper']))} == {
        "kind": "interval",
        "lower": "100",
        "upper": "300",
        "lower_closed": False,
        "upper_closed": True,
    }


def test_units_and_definition_both_must_match():
    with pytest.raises(DomainError, match="量纲相同"):
        SameQuantityTransform(
            Representation(kind="linear"),
            Representation(kind="linear"),
            "m",
            "m",
            source_quantity_key="radius",
            target_quantity_key="distance",
        )
    with pytest.raises(DomainError):
        transform(source_unit="mas", target_unit="pc")


def test_no_optional_uncertainty_is_not_zero_uncertainty():
    result = normalize(measurement(value="0"), transform())
    assert result["main_state"] == "ready"
    assert result["uncertainty_typed"]["components"] == []
    assert result["uncertainty_typed"]["state"] == "not_reported"


def test_numeric_checker_does_not_swallow_tiny_errors_with_absolute_tolerance():
    with pytest.raises(DomainError):
        verify_model_numbers({"value": "2e-20"}, {"value": "1e-20"})
    with pytest.raises(DomainError):
        verify_model_numbers({"value": "1e-100"}, {"value": "0"})
    verify_model_numbers({"value": "1.0000000001e-20"}, {"value": "1e-20"})


def test_quality_routes_by_specific_issue_and_recomputes_after_repair():
    record = measurement()
    pre = assess(
        [record],
        [],
        ["synthetic-property"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
        phase="precheck",
    )
    assert pre["overall_score"] is None
    assert pre["processing_items"][0]["kind"] == "convert_same_quantity"
    final = assess(
        [record],
        [derived(record)],
        ["synthetic-property"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
    )
    assert final["overall_score"] == 100
    assert final["issues"] == []


def test_properties_equal_weight_and_same_source_does_not_multiply_trust():
    records = [
        measurement("a", "p1", "s1"),
        measurement("b", "p1", "s1"),
        measurement("c", "p2", "s2"),
    ]
    result = assess(
        records,
        [derived(records[0]), derived(records[1], "partial"), derived(records[2])],
        ["p1", "p2"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
    )
    assert len(result["groups"]) == 2
    assert result["overall_score"] == 75
    # Adding many unchanged duplicates never gives the first property more weight.
    more = [measurement("d", "p1", "s1")]
    again = assess(
        records + more,
        [
            derived(records[0]),
            derived(records[1], "partial"),
            derived(records[2]),
            derived(more[0]),
        ],
        ["p1", "p2"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
    )
    assert again["overall_score"] == 75


def test_quality_missing_optional_errors_and_property_coverage_do_not_penalize_source():
    record = measurement()
    result = assess(
        [record],
        [derived(record)],
        ["synthetic-property", "unreported-property"],
        snapshot_ref=ref(),
        source_groups={},
        source_cautions={},
    )
    assert result["overall_score"] == 100
    assert result["score_scope"]["evaluated_property_count"] == 1


def test_differences_unknown_required_conditions_are_not_equal():
    records = [measurement("one"), measurement("two", value="3")]
    bindings = [
        {
            "property_id": "synthetic-property",
            "definition": {
                "measurement_conditions_schema": [{"key": "band", "required_for_comparison": True}]
            },
            "output_profile": {"version": 1},
        }
    ]
    result = compare(records, list(map(derived, records)), [], bindings, ref())
    assert result["groups"] == []
    assert len(result["limitations"]) == 2
    assert result["additional_source_reads"] == 0


def test_comparable_differences_are_summaries_not_error_or_best_value():
    records = [measurement("one"), measurement("two", value="3"), measurement("three", value="4")]
    bindings = [
        {
            "property_id": "synthetic-property",
            "definition": {"measurement_conditions_schema": []},
            "output_profile": {"version": 1},
        }
    ]
    result = compare(records, list(map(derived, records)), [], bindings, ref())
    assert len(result["groups"]) == 1
    assert len(result["groups"][0]["measurement_ids"]) == 3
    assert result["groups"][0]["cause"] == "unknown"
    assert result["model_calls"] == 0
    assert "best" not in str(result)
