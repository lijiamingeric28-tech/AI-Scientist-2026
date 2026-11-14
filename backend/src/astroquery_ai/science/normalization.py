"""Generic same-quantity representation checker, not a per-catalog rule engine.

Models propose source semantics and results. This module recomputes the declared
transformation and each uncertainty component; it never executes model code.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext, Underflow

from astroquery_ai.registry.models import Representation
from astroquery_ai.runtime.codec import digest, decimal_literal
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import SourceMeasurement

D = Decimal
MATH_POLICY = {
    "version": 5,
    'error_coordinates': 'source_representation_units',
    "minimum_precision": 80,
    "maximum_precision": 8192,
    "guard_digits": 32,
    "underflow": "reject",
    "epsilon": "0.20",
}


def math_context(ctx, *values):
    sizes = [len(value.as_tuple().digits) for value in values if isinstance(value, Decimal)]
    ctx.prec = min(8192, max(80, ctx.prec, 2 * max(sizes, default=1) + 32))
    ctx.traps[Underflow] = True


def number(value: str) -> Decimal:
    return D(decimal_literal(value))


def text(value: Decimal) -> str:
    if not value.is_finite():
        raise DomainError("NONFINITE_TRANSFORM", "变换产生非有限数值")
    return str(value)


class SameQuantityTransform:
    def __init__(
        self,
        source: Representation,
        target: Representation,
        source_unit: str,
        target_unit: str,
        *,
        source_quantity_key: str,
        target_quantity_key: str,
    ):
        if source_quantity_key != target_quantity_key:
            raise DomainError("DIFFERENT_QUANTITY", "量纲相同不能授权不同性质间转换")
        if source.kind not in {"linear", "log10", "ln", "magnitude"} or target.kind not in {
            "linear",
            "log10",
            "ln",
            "magnitude",
        }:
            raise DomainError("UNSUPPORTED_TRANSFORM", "该变换器只处理有据数值表示")
        from .units import decimal_unit_factor

        native_only = source.native_coordinate_only or target.native_coordinate_only
        from .units import native_coordinate_unit_equal
        # Restriction flags and evidence IDs are not numerical parameters.
        # The exact same coordinate may have a fully known source basis while
        # the output policy deliberately permits identity only. This never
        # supplies a missing basis, scale, offset or photometric system.
        math_fields=('kind','scale','offset','reference_value','reference_unit','system_ref')
        same_parameters=all(getattr(source,k)==getattr(target,k) for k in math_fields)
        native_identity = same_parameters and native_coordinate_unit_equal(source_unit, target_unit, source.kind)
        if native_only and not native_identity:
            raise DomainError('NATIVE_COORDINATE_ONLY', '缺数值基准时仅保留同一原生坐标，不能执行对数或单位变换')
        try:
            # No parallax/spectral/doppler or other cross-quantity equivalencies.
            self.factor = (D(1) if native_only and native_identity or source == target and source_unit == target_unit else
                decimal_unit_factor(source.reference_unit if source.kind != "linear" else source_unit,
                    target.reference_unit if target.kind != "linear" else target_unit))
        except (ValueError, TypeError) as exc:
            raise DomainError(
                "UNIT_CONVERSION_UNSUPPORTED", "源/目标单位不能执行当前同量变换"
            ) from exc
        self.source, self.target = source, target
        self.source_unit, self.target_unit = source_unit, target_unit
        self.coordinate_identity = (source == target or native_only and native_identity) and self.factor == 1
        if (not native_only and source.kind == target.kind and source.kind in {'log10', 'ln', 'magnitude'}
                and source.scale == target.scale and source.offset == target.offset and source.system_ref == target.system_ref):
            self.coordinate_identity = number(source.reference_value) * self.factor == number(target.reference_value)
        self.affine = source.kind == target.kind == "linear" or native_only or self.coordinate_identity
        self.transform_ref = {
            "id": "transform-"
            + digest(
                {
                    "source": source.model_dump(),
                    "target": target.model_dump(),
                    "source_unit": source_unit,
                    "target_unit": target_unit,
                    "quantity": source_quantity_key,
                }
            ),
            "version": 1,
            "content_sha256": digest(
                {
                    "source": source.model_dump(),
                    "target": target.model_dump(),
                    "factor": str(self.factor),
                }
            ),
        }

    @staticmethod
    def _base(rep):
        return D(10) if rep.kind in {"log10", "magnitude"} else D(1).exp()

    def _decode(self, x):
        rep = self.source
        if rep.kind == "linear":
            return number(rep.scale) * x + number(rep.offset)
        # Magnitudes are the same finite log representation with explicitly signed multiplier.
        exponent = (x - number(rep.offset)) / number(rep.scale)
        return number(rep.reference_value) * (self._base(rep) ** exponent)

    def apply(self, x: Decimal) -> Decimal:
        with localcontext() as ctx:
            math_context(ctx, x)
            if self.coordinate_identity:
                return x
            q = self._decode(x) * self.factor
            rep = self.target
            if rep.kind == "linear":
                result = (q - number(rep.offset)) / number(rep.scale)
            else:
                if q <= 0:
                    raise DomainError("TRANSFORM_DOMAIN", "目标对数表示要求正的物理量")
                result = (q / number(rep.reference_value)).ln() / self._base(rep).ln() * number(
                    rep.scale
                ) + number(rep.offset)
            if not result.is_finite():
                raise DomainError("TRANSFORM_DOMAIN", "变换结果超出定义域")
            return +result

    def derivative(self, x):
        if self.coordinate_identity:
            return D(1)
        with localcontext() as ctx:
            math_context(ctx, x)
            s, t = self.source, self.target
            q = self._decode(x) * self.factor
            dq = (
                number(s.scale) * self.factor
                if s.kind == "linear"
                else self._decode(x) * self._base(s).ln() / number(s.scale) * self.factor
            )
            if t.kind == "linear":
                return +(dq / number(t.scale))
            if q <= 0:
                raise DomainError("TRANSFORM_DOMAIN", "对数导数定义域错误")
            return +(number(t.scale) / (q * self._base(t).ln()) * dq)

    def check_first_order(self, x, magnitude, sides=(-1, 1), epsilon=D("0.20")) -> dict:
        j = self.derivative(x)
        if magnitude < 0:
            raise DomainError("NEGATIVE_ERROR", "误差幅度不能为负")
        if magnitude and j == 0:
            raise DomainError("FIRST_ORDER_NOT_APPLICABLE", "局部导数为零")
        deviations = []
        for side in sides:
            edge = x + side * magnitude
            edge_j = self.derivative(edge)
            if j * edge_j <= 0:
                raise DomainError("FIRST_ORDER_NOT_APPLICABLE", "检查段不在同一单调分支")
            linear = abs(j) * magnitude
            actual = abs(self.apply(edge) - self.apply(x))
            deviation = abs(actual - linear) / linear if linear else D(0)
            if deviation > epsilon:
                raise DomainError("FIRST_ORDER_NOT_APPLICABLE", "局部线性偏差超过已登记上限")
            deviations.append(text(deviation))
        return {
            "derivative": text(j),
            "magnitude": text(magnitude),
            "epsilon": text(epsilon),
            "deviations": deviations,
        }

    def value(self, value: dict) -> dict:
        if value["kind"] in {"real", "integer"}:
            return {"kind": "real", "value": text(self.apply(number(value["value"])))}
        if value["kind"] != "interval":
            raise DomainError("VALUE_TRANSFORM_UNSUPPORTED", "非数值不能执行数值变换")
        lower = self.apply(number(value["lower"])) if value["lower"] is not None else None
        upper = self.apply(number(value["upper"])) if value["upper"] is not None else None
        point = number(value["lower"] if value["lower"] is not None else value["upper"])
        lc, uc = value["lower_closed"], value["upper_closed"]
        if self.derivative(point) < 0:
            lower, upper, lc, uc = upper, lower, uc, lc
        return {
            "kind": "interval",
            "lower": text(lower) if lower is not None else None,
            "upper": text(upper) if upper is not None else None,
            "lower_closed": lc,
            "upper_closed": uc,
        }

    def component(
        self,
        component: dict,
        x: Decimal,
        *,
        basis_values: dict[str, str],
        target_unit_ref: dict,
        target_representation_ref: dict,
        source_component_unit: str | None = None,
    ) -> dict:
        result = {
            "source_component_id": component["component_id"],
            "raw_component_ref": component["component_id"],
            "status": "source_unresolved",
            "output_component": None,
            "method": "source_preserved",
            "transform_ref": self.transform_ref,
            "validation_ref": None,
            "reason": component.get("reason"),
        }
        if component["interpretation_state"] == "unresolved":
            return result
        output = deepcopy(component)
        kind, values = component["kind"], deepcopy(component["values"])
        try:
            if source_component_unit is not None and kind not in {
                "relative",
                "percent",
                "covariance",
                "correlation",
            }:
                from astropy import units as u

                power = 2 if kind == "variance" else -2 if kind == "inverse_variance" else 1
                # Errors live in source coordinates: a dex/mag error is not a
                # length/flux error even when the log reference has that unit.
                coordinate = {'log10': u.dex, 'ln': u.dimensionless_unscaled,
                              'magnitude': u.mag}.get(self.source.kind)
                if coordinate is None:
                    coordinate = u.Unit(self.source_unit)
                expected = coordinate ** power
                from .units import decimal_unit_factor
                factor = decimal_unit_factor(source_component_unit, str(expected))
                for key, value in values.items():
                    if key not in {"kind", "lower_closed", "upper_closed"} and value is not None:
                        values[key] = text(number(value) * factor)
            j = self.derivative(x)
            validations = []
            endpoint = component["statistical_meaning"] in {
                "confidence_interval",
                "credible_interval",
                "quantile_bounds",
            }
            if kind == "interval_endpoints":
                output["values"] = self.value(values)
                method = "endpoint_mapping"
            elif kind in {"covariance", "correlation"}:
                raise DomainError("AXIS_TRANSFORM_REQUIRED", "矩阵需关联轴完整映射，本项保留原矩阵")
            else:
                if kind in {"relative", "percent"}:
                    ref = component.get("basis_ref")
                    if not ref or ref["id"] not in basis_values:
                        raise DomainError("ERROR_BASIS_UNKNOWN", "缺少来源明确的相对误差基准")
                    basis = abs(number(basis_values[ref["id"]]))
                    multiplier = basis / (D(100) if kind == "percent" else D(1))
                else:
                    multiplier = D(1)
                if "delta" in values:
                    d = number(values["delta"]) * multiplier
                    if kind == "variance":
                        d = d.sqrt()
                    elif kind == "inverse_variance":
                        if d <= 0:
                            raise DomainError("INVALID_INVERSE_VARIANCE", "逆方差必须为正")
                        d = (D(1) / d).sqrt()
                    sides = {"minus": d, "plus": d}
                else:
                    sides = {
                        side: number(v) * multiplier if v is not None else None
                        for side, v in values.items()
                    }
                if endpoint:
                    source_interval = {
                        "kind": "interval",
                        "lower": text(x - sides["minus"]) if sides["minus"] is not None else None,
                        "upper": text(x + sides["plus"]) if sides["plus"] is not None else None,
                        "lower_closed": True,
                        "upper_closed": True,
                    }
                    output["kind"], output["values"] = (
                        "interval_endpoints",
                        self.value(source_interval),
                    )
                    method = "endpoint_mapping"
                else:
                    if not self.affine:
                        for side, magnitude in sides.items():
                            if magnitude is not None:
                                validations.append(
                                    self.check_first_order(
                                        x, magnitude, (-1,) if side == "minus" else (1,)
                                    )
                                )
                    mapped = {
                        side: abs(j) * magnitude if magnitude is not None else None
                        for side, magnitude in sides.items()
                    }
                    if j < 0:
                        mapped["minus"], mapped["plus"] = mapped["plus"], mapped["minus"]
                    if kind == "variance":
                        output["values"] = {"delta": text(j * j * number(values["delta"]))}
                    elif kind == "inverse_variance":
                        if j == 0:
                            raise DomainError("ZERO_DERIVATIVE", "逆方差无法在零导数下传播")
                        output["values"] = {"delta": text(number(values["delta"]) / (j * j))}
                    elif "delta" in values:
                        output["kind"], output["values"] = (
                            "symmetric_delta",
                            {"delta": text(mapped["minus"])},
                        )
                    else:
                        output["kind"], output["values"] = (
                            "asymmetric_delta",
                            {
                                side: text(v) if v is not None else None
                                for side, v in mapped.items()
                            },
                        )
                    method = "affine_delta" if self.affine else "first_order"
            output["unit_ref"], output["representation_ref"] = (
                target_unit_ref,
                target_representation_ref,
            )
            if output["kind"] in {"variance", "inverse_variance"}:
                from .units import parse_unit
                power = 2 if output["kind"] == "variance" else -2
                definition = {
                    "base_unit_ref": target_unit_ref,
                    "power": power,
                    "canonical_symbol": (parse_unit(self.target_unit) ** power).to_string(),
                    "quantity_role": output["kind"],
                }
                definition["unit_id"] = "derived-error-unit-" + digest(definition)
                output["unit_ref"] = {
                    "id": definition["unit_id"],
                    "version": 1,
                    "content_sha256": digest(definition),
                }
                result["unit_definition"] = definition
            check = {
                "receipt_id": "validation-"
                + digest(
                    {
                        "transform": self.transform_ref,
                        "component": component,
                        "diagnostics": validations,
                    }
                ),
                "source_component_id": component["component_id"],
                "transform_ref": self.transform_ref,
                "diagnostics": validations,
                "status": "passed",
                "method": method,
            }
            result.update(
                status="approximate" if method == "first_order" else "exact",
                output_component=output,
                method=method,
                validation_receipt=check,
                validation_ref={
                    "id": check["receipt_id"],
                    "version": 1,
                    "content_sha256": digest(check),
                },
                reason=None,
            )
        except (DomainError, ArithmeticError, ValueError) as exc:
            result.update(
                status="unsupported",
                reason=exc.code if isinstance(exc, DomainError) else "arithmetic_domain",
            )
        return result


def normalize_checked(
    measurement: SourceMeasurement,
    transform: SameQuantityTransform,
    output_profile_ref: dict,
    *,
    target_unit_ref: dict,
    target_representation_ref: dict,
    basis_values=None,
    component_units=None,
) -> dict:
    source = measurement.model_dump(mode="json")
    result = {
        "schema_version": "DerivedRepresentation/2",
        "derived_id": "derived-"
        + digest(
            {
                "source": source["content_sha256"],
                "profile": output_profile_ref,
                "transform": transform.transform_ref,
                "execution_policy": digest(MATH_POLICY),
            }
        ),
        "measurement_id": source["measurement_id"],
        "source_representation_hash": source["content_sha256"],
        "output_profile_ref": output_profile_ref,
        "execution_profile_ref": {
            "id": "normalization-math-" + str(MATH_POLICY['version']),
            "version": MATH_POLICY['version'],
            "content_sha256": digest(MATH_POLICY),
        },
        "status": "failed",
        "main_state": "failed",
        "value_typed": None,
        "uncertainty_typed": None,
        "limit": source["limit"],
        "transform_ref": transform.transform_ref,
        'coordinate_units': {'source': transform.source_unit, 'target': transform.target_unit,
            'basis': 'source_declaration_and_frozen_target_encoding'},
        "approximation_present": False,
        "issues": [],
        "validation_receipt_ref": None,
    }
    try:
        with localcontext() as ctx:

            def scalars(value):
                if isinstance(value, dict):
                    return [n for v in value.values() for n in scalars(v)]
                if isinstance(value, list):
                    return [n for v in value for n in scalars(v)]
                if isinstance(value, str):
                    try:
                        return [number(value)]
                    except ValueError:
                        pass
                return []

            math_context(ctx, *scalars(source))
            result["value_typed"] = transform.value(source["value"])
            result["main_state"] = "ready"
            if source["value"]["kind"] in {"real", "integer"}:
                x = number(source["value"]["value"])
                if source["limit"] != "none" and transform.derivative(x) < 0:
                    result["limit"] = {
                        "upper": "lower",
                        "lower": "upper",
                        "upper_open": "lower_open",
                        "lower_open": "upper_open",
                    }[source["limit"]]
            elif source["uncertainty"]["components"]:
                raise DomainError(
                    "INTERVAL_ERROR_CENTRE_MISSING", "主值仅区间，不能捏造误差传播中心"
                )
            else:
                x = D(0)
            components = [
                transform.component(
                    c,
                    x,
                    basis_values=basis_values or {},
                    target_unit_ref=target_unit_ref,
                    target_representation_ref=target_representation_ref,
                    source_component_unit=(component_units or {}).get(
                        (c.get("unit_ref") or {}).get("id")
                    ),
                )
                for c in source["uncertainty"]["components"]
            ]
            gap = any(c["status"] in {"unsupported", "failed", "not_run"} for c in components)
            result["uncertainty_typed"] = {
                "contract_version": "UncertaintyBundle/1",
                "source_bundle_ref": digest(source["uncertainty"]),
                "components": components,
                "state": 'source_unresolved'
                if source['uncertainty']['state'] == 'unresolved'
                else "partial" if gap
                else "not_reported"
                if source["uncertainty"]["state"] == "not_reported"
                else "source_unresolved"
                if source["uncertainty"]["state"] == "unresolved"
                else "ready",
            }
            result["status"] = "partial" if gap else "ready"
            result["approximation_present"] = any(c["status"] == "approximate" for c in components)
    except (DomainError, ArithmeticError, ValueError) as exc:
        result["issues"].append(
            {"code": exc.code if isinstance(exc, DomainError) else "TRANSFORM_DOMAIN"}
        )
        if result["main_state"] == "ready":
            result["status"] = "partial"
            result["uncertainty_typed"] = {
                "contract_version": "UncertaintyBundle/1",
                "source_bundle_ref": digest(source["uncertainty"]),
                "state": "partial",
                "components": [
                    {
                        "source_component_id": c["component_id"],
                        "status": "unsupported",
                        "output_component": None,
                        "method": "source_preserved",
                        "raw_component_ref": c["component_id"],
                        "reason": "interval_centre_unavailable",
                    }
                    for c in source["uncertainty"]["components"]
                ],
            }
    check = {
        "receipt_id": "check-" + result["derived_id"],
        "source_hash": source["content_sha256"],
        "output_profile_ref": output_profile_ref,
        "checker": "independent-math-1",
        "main_state": result["main_state"],
        "component_outcomes": [
            {"component_id": c["source_component_id"], "status": c["status"]}
            for c in (result["uncertainty_typed"] or {}).get("components", [])
        ],
    }
    result["validation_receipt"] = check
    result["validation_receipt_ref"] = {
        "id": check["receipt_id"],
        "version": 1,
        "content_sha256": digest(check),
    }
    return result


def verify_model_numbers(proposed: dict, checked: dict, rtol=D("1e-9")):
    """Compare complete structured numeric results, including components by ID."""

    def compare(expected, actual, path):
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or set(actual) != set(expected):
                raise DomainError("MODEL_RESULT_SHAPE", "模型结果字段不完整", path=path)
            for key, value in expected.items():
                compare(value, actual[key], path + "." + key)
        elif isinstance(expected, list):
            if not isinstance(actual, list) or len(expected) != len(actual):
                raise DomainError("MODEL_RESULT_SHAPE", "模型结果组件不完整", path=path)
            if path == 'result.components':
                if any(not isinstance(c, dict) or not isinstance(c.get('source_component_id'), str) for c in actual):
                    raise DomainError('MODEL_RESULT_SHAPE', '模型误差组件缺少源组件标识', path=path)
                by_id = {c['source_component_id']: c for c in actual}
                if len(by_id) != len(actual) or set(by_id) != {c['source_component_id'] for c in expected}:
                    raise DomainError('MODEL_RESULT_SHAPE', '模型误差组件重复、缺失或越权', path=path)
                actual = [by_id[c['source_component_id']] for c in expected]
            for i, (a, b) in enumerate(zip(expected, actual)):
                compare(a, b, f"{path}[{i}]")
        elif isinstance(expected, str):
            try:
                value = number(expected)
            except ValueError:
                if expected != actual:
                    raise DomainError("MODEL_SEMANTIC_CHANGE", "模型结果改写了只读语义", path=path)
            else:
                if not isinstance(actual, str):
                    raise DomainError(
                        "MODEL_RESULT_NUMBER", "模型数值必须为十进制字符串", path=path
                    )
                other = number(actual)
                if abs(value - other) > abs(value) * rtol:
                    raise DomainError(
                        "MODEL_NUMERIC_CHECK_FAILED", "模型数值与独立验算不符", path=path
                    )
        elif expected != actual or type(expected) is not type(actual):
            raise DomainError("MODEL_SEMANTIC_CHANGE", "模型结果与核验结构不符", path=path)

    compare(checked, proposed, "result")
