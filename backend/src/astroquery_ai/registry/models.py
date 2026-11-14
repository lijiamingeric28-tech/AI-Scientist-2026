from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator, model_serializer

from astroquery_ai.runtime.codec import decimal_literal
from astroquery_ai.runtime.models import Contract, Identifier, Ref, Sha256


class Unit(Contract):
    kind: Literal["physical", "dimensionless", "not_applicable"]
    canonical_symbol: str | None = None
    dimension: str | None = None
    parser_format: Literal["cds", "vounit", "generic", "source_literal"] | None = None
    parser_version: str | None = None
    semantic_kind: str | None = None

    @model_validator(mode="after")
    def unit_kind(self):
        if self.kind == "physical" and not all(
            (self.canonical_symbol, self.dimension, self.parser_format, self.parser_version)
        ):
            raise ValueError("physical unit requires parser and dimension")
        if self.kind == "dimensionless" and not self.semantic_kind:
            raise ValueError("dimensionless must retain scientific semantic kind")
        if self.kind == "not_applicable" and any(
            (self.canonical_symbol, self.dimension, self.semantic_kind)
        ):
            raise ValueError("non-numeric unit must be not_applicable without numeric metadata")
        return self


class Representation(Contract):
    kind: Literal["linear", "log10", "ln", "magnitude", "category", "boolean", "text", "relation"]
    scale: str = "1"
    offset: str = "0"
    reference_value: str | None = None
    reference_unit: str | None = None
    system_ref: Ref | None = None
    evidence_refs: list[Ref] = Field(default_factory=list)
    native_coordinate_only: bool = False

    @model_serializer(mode='wrap')
    def preserve_legacy_encoding(self, handler):
        result = handler(self)
        if not self.native_coordinate_only:
            result.pop('native_coordinate_only', None)
        return result

    @model_validator(mode="after")
    def parameters(self):
        from decimal import Decimal

        decimal_literal(self.scale)
        decimal_literal(self.offset)
        if Decimal(self.scale) == 0:
            raise ValueError("zero representation scale")
        if self.native_coordinate_only and self.kind not in {'log10', 'ln', 'magnitude'}:
            raise ValueError('native coordinate restriction is only for logarithmic coordinates')
        if self.kind in {"log10", "ln", "magnitude"} and not self.native_coordinate_only:
            if self.reference_value is None or self.reference_unit is None:
                raise ValueError("log/magnitude requires explicit reference")
            decimal_literal(self.reference_value)
            if Decimal(self.reference_value) <= 0:
                raise ValueError("non-positive reference")
        if self.kind == "magnitude" and self.system_ref is None and not self.native_coordinate_only:
            raise ValueError("magnitude requires a photometric system")
        return self


class Explanation(Contract):
    subject: str = Field(min_length=1)
    quantity: str = Field(min_length=1)
    boundary: str = Field(min_length=1)
    representation: str = Field(min_length=1)
    distinctions: list[str]
    evidence_scope: str = Field(min_length=1)


class ValueSchema(Contract):
    kind: Literal["real", "integer", "category", "boolean", "text", "relation"]
    categories: dict[str, str] = Field(default_factory=dict)
    predicate_id: str | None = None
    subject_role: str | None = None
    object_role: str | None = None

    @model_validator(mode="after")
    def proper_shape(self):
        if self.kind == "category" and not self.categories:
            raise ValueError("category requires reviewed code meanings")
        if self.kind == "relation" and not all(
            (self.predicate_id, self.subject_role, self.object_role)
        ):
            raise ValueError("relation requires defined roles")
        return self


class ConditionSchema(Contract):
    key: Identifier
    value_type: Literal["text", "decimal", "integer", "boolean", "enum", "reference"]
    required_for_identity: bool
    required_for_comparison: bool
    allowed_values: list[str] = Field(default_factory=list)
    missing_policy: Literal["limit_comparison", "block_admission", "optional", "retain_unknown"]
    required_scope: str = "all_sources"


class PropertyDefinition(Contract):
    property_id: Identifier
    definition_version: int = Field(ge=1)
    content_sha256: Sha256
    name_cn: str = Field(min_length=1)
    name_en: str | None
    name_en_missing_reason: str | None = None
    aliases: list[str]
    description: str = Field(min_length=1)
    distinction_notes: list[str]
    quantity_key: Identifier
    quantity_kind: Identifier
    scientific_purpose: str = Field(min_length=1)
    subject_class_id: Identifier
    scope: Literal[
        "whole_object", "bounded_whole", "whole_system_relation", "target_environment_relation"
    ]
    definition_qualifiers: dict[str, JsonValue]
    measurement_conditions_schema: list[ConditionSchema]
    value_schema: ValueSchema
    family_id: Identifier
    ucd: dict[str, str | Ref]
    evidence_refs: list[Ref] = Field(min_length=1)
    review_ref: Ref
    explanation: Explanation


class OutputProfile(Contract):
    profile_id: Identifier
    version: int = Field(ge=1)
    content_sha256: Sha256
    property_id: Identifier
    definition_version: int = Field(ge=1)
    object_scale_id: Identifier
    unit: Unit
    representation: Representation
    conversion_policy_ref: Ref
    review_ref: Ref


class PropertyBinding(Contract):
    property_id: Identifier
    definition: PropertyDefinition
    output_profile: OutputProfile
    dependency_refs: list[Ref] = Field(min_length=1)
    rule_refs: list[Ref] = Field(min_length=1)

    @model_validator(mode="after")
    def same_definition(self):
        if (
            self.property_id != self.definition.property_id
            or self.property_id != self.output_profile.property_id
            or self.definition.definition_version != self.output_profile.definition_version
        ):
            raise ValueError("binding identity mismatch")
        numeric = self.definition.value_schema.kind in {"real", "integer"}
        if numeric == (self.output_profile.unit.kind == "not_applicable"):
            raise ValueError("value and output unit type conflict")
        if (
            not numeric
            and self.output_profile.representation.kind != self.definition.value_schema.kind
        ):
            raise ValueError("non-numeric representation conflicts with definition")
        return self
