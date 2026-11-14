"""Strict scientific and control contracts; no legacy string-value coercion."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from .codec import decimal_literal

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DecimalText = Annotated[str, Field(min_length=1, max_length=4096)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class Ref(Contract):
    id: Identifier
    version: int = Field(ge=1)
    content_sha256: Sha256


class VersionedIdentity(Contract):
    """Back-reference uses ID+version to avoid a cycle of content hashes."""

    id: Identifier
    version: int = Field(ge=1)


class EvidenceHandle(Contract):
    evidence_id: Identifier
    artifact_ref: Ref
    source_id: Identifier
    kind: Literal["paper", "catalog", "official_attachment", "identity"]
    locator: dict[str, Union[str, int, list[int]]]
    raw_text: str | None = None
    available: bool
    scope: str
    truncated: bool = False


class ScalarValue(Contract):
    kind: Literal["real", "integer"]
    value: DecimalText

    @field_validator("value")
    @classmethod
    def finite(cls, value):
        return decimal_literal(value)

    @model_validator(mode="after")
    def integer_value(self):
        from decimal import Decimal

        if (
            self.kind == "integer"
            and Decimal(self.value) != Decimal(self.value).to_integral_value()
        ):
            raise ValueError("integer value must be integral")
        return self


class IntervalValue(Contract):
    kind: Literal["interval"]
    lower: DecimalText | None
    upper: DecimalText | None
    lower_closed: bool
    upper_closed: bool

    @model_validator(mode="after")
    def bounds(self):
        from decimal import Decimal

        for value in (self.lower, self.upper):
            if value is not None:
                decimal_literal(value)
        if self.lower is None and self.upper is None:
            raise ValueError("interval requires a bound")
        if (
            self.lower is not None
            and self.upper is not None
            and Decimal(self.lower) > Decimal(self.upper)
        ):
            raise ValueError("reversed interval")
        return self


class CategoryValue(Contract):
    kind: Literal["category"]
    code: Identifier
    raw_label: str


class BooleanValue(Contract):
    kind: Literal["boolean"]
    value: bool


class TextValue(Contract):
    kind: Literal["text"]
    value: str


class OtherEntity(Contract):
    authority: str | None
    identifier: str | None
    raw_name: str


class RelationValue(Contract):
    kind: Literal["relation"]
    predicate_id: Identifier
    subject_role: Identifier
    object_role: Identifier
    direction: Literal["outgoing", "incoming", "symmetric"]
    other_entity: OtherEntity
    assertion_status: Literal["confirmed", "candidate", "uncertain"]
    source_probability: DecimalText | None = None

    @field_validator("source_probability")
    @classmethod
    def probability(cls, value):
        if value is not None:
            from decimal import Decimal

            decimal_literal(value)
            if not 0 <= Decimal(value) <= 1:
                raise ValueError("probability outside [0,1]")
        return value


ScientificValue = Annotated[
    Union[ScalarValue, IntervalValue, CategoryValue, BooleanValue, TextValue, RelationValue],
    Field(discriminator="kind"),
]


class Delta(Contract):
    delta: DecimalText


class Sides(Contract):
    minus: DecimalText | None
    plus: DecimalText | None


class MatrixValue(Contract):
    matrix: list[list[DecimalText | None]]


class ErrorLevel(Contract):
    kind: Literal[
        "confidence_probability",
        "credible_probability",
        "coverage_factor",
        "sigma_label",
        "quantile_levels",
    ]
    values: list[DecimalText]
    raw_text: str
    evidence_refs: list[Ref] = Field(min_length=1)

    @model_validator(mode="after")
    def finite_level(self):
        from decimal import Decimal

        if not self.values:
            raise ValueError("source level needs values")
        for value in self.values:
            decimal_literal(value)
            if (
                self.kind in {"confidence_probability", "credible_probability", "quantile_levels"}
                and not 0 <= Decimal(value) <= 1
            ):
                raise ValueError("level probability outside [0,1]")
            if self.kind in {"coverage_factor", "sigma_label"} and Decimal(value) <= 0:
                raise ValueError("non-positive level factor")
        return self


class UncertaintyComponent(Contract):
    component_id: Identifier
    interpretation_state: Literal["parsed", "unresolved"]
    kind: Literal[
        "symmetric_delta",
        "asymmetric_delta",
        "interval_endpoints",
        "relative",
        "percent",
        "variance",
        "inverse_variance",
        "covariance",
        "correlation",
        "other_reported",
    ]
    values: Union[Delta, Sides, IntervalValue, MatrixValue, None]
    role: Literal["stat", "sys", "total", "unspecified"]
    raw_label: str | None = None
    statistical_meaning: Literal[
        "standard_uncertainty",
        "expanded_uncertainty",
        "confidence_interval",
        "credible_interval",
        "quantile_bounds",
        "reported_error",
        "unspecified",
    ]
    level: ErrorLevel | None
    representation_ref: Ref | None
    unit_ref: Ref | None
    basis_ref: Ref | None
    axes: list[Ref] = Field(default_factory=list)
    dependency_refs: list[Ref] = Field(default_factory=list)
    evidence_refs: list[Ref] = Field(min_length=1)
    raw_text: str
    interpretation_provenance: Ref
    reason: str | None = None
    value_adaptation: dict[str, JsonValue] | None = None

    @model_serializer(mode="wrap")
    def optional_value_adaptation(self, handler):
        value = handler(self)
        if self.value_adaptation is None:
            value.pop("value_adaptation", None)
        return value

    @model_validator(mode="after")
    def valid_component(self):
        from decimal import Decimal

        if self.interpretation_state == "unresolved":
            if self.values is not None or not self.reason or not self.raw_text:
                raise ValueError(
                    "unresolved component needs original text/reason and no guessed values"
                )
            return self
        if self.values is None:
            raise ValueError("parsed component requires values")
        if self.kind in {"symmetric_delta", "variance", "inverse_variance"} and not isinstance(
            self.values, Delta
        ):
            raise ValueError("scalar uncertainty requires delta field")
        if self.kind == "asymmetric_delta" and not isinstance(self.values, Sides):
            raise ValueError("asymmetric uncertainty requires separate sides")
        if self.kind in {"relative", "percent"}:
            if not isinstance(self.values, (Delta, Sides)) or self.basis_ref is None:
                raise ValueError("relative uncertainty requires explicit source basis")
        if self.kind == "interval_endpoints" and not isinstance(self.values, IntervalValue):
            raise ValueError("endpoint uncertainty requires interval")
        if self.kind in {"covariance", "correlation"}:
            if not isinstance(self.values, MatrixValue) or not self.axes:
                raise ValueError("matrix uncertainty requires axes")
            if len(self.values.matrix) != len(self.axes) or any(
                len(row) != len(self.axes) for row in self.values.matrix
            ):
                raise ValueError("matrix dimensions do not match axes")

        def numbers(value):
            if isinstance(value, str):
                decimal_literal(value)
                if (
                    self.kind not in {"interval_endpoints", "covariance", "correlation"}
                    and Decimal(value) < 0
                ):
                    raise ValueError("negative uncertainty magnitude")
            elif isinstance(value, list):
                for item in value:
                    numbers(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in {"kind", "lower_closed", "upper_closed"}:
                        numbers(item)

        numbers(self.values.model_dump())
        if (
            isinstance(self.values, Sides)
            and self.values.minus is None
            and self.values.plus is None
        ):
            raise ValueError("both uncertainty sides are missing")
        return self


class UncertaintyBundle(Contract):
    contract_version: Literal["UncertaintyBundle/1"] = "UncertaintyBundle/1"
    state: Literal["not_reported", "reported", "unresolved"]
    components: list[UncertaintyComponent]
    raw_refs: list[Ref]
    reason: str | None
    inspection_ref: Ref

    @model_validator(mode="after")
    def valid_state(self):
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate uncertainty component IDs")
        if self.state == "not_reported" and self.components:
            raise ValueError("not_reported cannot contain components")
        if self.state != "not_reported" and not self.components:
            raise ValueError("reported uncertainty requires components")
        if self.state == "unresolved" and (
            not self.reason or any(c.interpretation_state == "parsed" for c in self.components)
        ):
            raise ValueError("invalid unresolved bundle")
        if self.state == "reported" and not any(
            c.interpretation_state == "parsed" for c in self.components
        ):
            raise ValueError("all components unresolved: use unresolved bundle")
        return self


class Condition(Contract):
    key: Identifier
    state: Literal["known", "not_reported", "not_checked", "unresolved", "not_applicable", "failed"]
    value: Union[str, bool, int, list[str], dict[str, JsonValue], None]
    representation_ref: Ref | None
    scope: Identifier
    evidence_refs: list[Ref]
    check_ref: Ref | None
    reason: str | None
    human_answer_ref: Ref | None = None

    @model_validator(mode="after")
    def known_has_evidence(self):
        if self.state == "known" and (
            self.value is None or not self.evidence_refs or self.check_ref is None
        ):
            raise ValueError("known condition requires value, evidence and check")
        if self.state != "known" and self.value is not None:
            raise ValueError("unknown condition must not carry a guessed value")
        return self


class ComparisonContext(Contract):
    contract_version: Literal["ComparisonContext/1"] = "ComparisonContext/1"
    context_id: Identifier
    revision: int = Field(ge=1)
    content_sha256: Sha256
    measurement_ref: VersionedIdentity
    source_ref: Ref
    snapshot_binding: dict[str, Ref]
    source_background_ref: Ref | None
    conditions: list[Condition]
    excerpt_refs: list[Ref]
    source_statements: list[Ref]
    lineage_refs: list[Ref]
    uncertainty_ref: Ref
    collection_receipt: Ref


class SourceUnitDeclaration(Contract):
    schema_version: Literal['SourceUnitDeclaration/1']
    kind: Literal['dimensionless', 'source_declared_unit']
    canonical_symbol: str = Field(min_length=1)
    raw_unit_text: None
    source_literal: str | None = Field(min_length=1)
    artifact_ref: Ref
    locator: dict[str, str | int]
    raw_quote: str = Field(min_length=1)
    rule: Literal['cds-numeric-unitless-1', 'cds-numeric-unit-1', 'evidenced_intrinsic_count_coordinate-1',
                  'independently_evidenced_dimensionless_log_coordinate-1']
    format_basis: str

    @model_validator(mode='after')
    def literal_or_intrinsic_count(self):
        if self.rule in {'evidenced_intrinsic_count_coordinate-1','independently_evidenced_dimensionless_log_coordinate-1'}:
            if self.source_literal is not None or self.kind!='dimensionless' or self.canonical_symbol!='1':
                raise ValueError('An intrinsic count keeps the native missing unit and coefficient1.')
        elif self.source_literal is None:
            raise ValueError('A CDS unit declaration needs its original literal.')
        return self


class SourceMeasurement(Contract):
    schema_version: Literal["SourceMeasurement/2"] = "SourceMeasurement/2"
    measurement_id: Identifier
    revision: int = Field(ge=1)
    task_id: Identifier
    query_ref: Ref
    target_ref: Ref
    property_ref: Ref
    source_ref: Ref
    interpretation_ref: Ref
    source_kind: Literal["paper", "catalog", "official_attachment"]
    value: ScientificValue
    raw_value: str
    unit: str | None
    unit_declaration: SourceUnitDeclaration | None = None
    representation: Literal[
        "linear", "log10", "ln", "magnitude", "category", "boolean", "text", "relation"
    ]
    limit: Literal["none", "upper", "lower", "upper_open", "lower_open"]
    uncertainty: UncertaintyBundle
    context_ref: Ref
    evidence_refs: list[Ref] = Field(min_length=1)
    admission_receipt_ref: Ref
    source_qualification_ref: Ref
    citation_state: Literal['seen','not_seen','unknown'] = 'unknown'
    lineage_refs: list[Ref] = Field(default_factory=list)
    content_sha256: Sha256

    @model_validator(mode="after")
    def numeric_unit(self):
        if isinstance(self.value, (ScalarValue, IntervalValue)) and self.unit is None and self.unit_declaration is None:
            raise ValueError("numeric source requires an explicit source unit")
        if not isinstance(self.value, ScalarValue) and self.limit != "none":
            raise ValueError("limit applies only to an explicit scalar bound")
        return self


TERMINAL = frozenset(
    {"completed", "error", "cancelled", "budget_exhausted", "definition_invalidated"}
)
LIFECYCLES = (
    frozenset(
        {
            "clarifying",
            "waiting_input",
            "queued",
            "running",
            "waiting_review",
            "paused",
            "interrupted",
            "pausing",
            "cancelling",
        }
    )
    | TERMINAL
)


class RuntimeErrorInfo(Contract):
    code: Identifier
    message: str
    stage: str
    retryable: bool
    scope_ids: list[str] = Field(default_factory=list)


class Operation(Contract):
    operation_id: Identifier
    expected_revision: int = Field(ge=1)
