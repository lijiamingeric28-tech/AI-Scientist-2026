"Producer proposal protocol; importing types does not load an extractor."

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, ValidationError, field_validator, model_serializer

from astroquery_ai.runtime.codec import content_hash

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import Contract, ScientificValue

from astroquery_ai.registry.models import Representation

from astroquery_ai.science.measurements.admission_contracts import AdmissionCheck, Anchor, CatalogScientificIssue


class CatalogSemanticAnchor(Contract):
    column: str
    quote: str = Field(min_length=1)
    aspect: Literal["role", "meaning", "level"]


class ErrorProposal(Contract):
    location: str
    raw_text: str
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
    values: dict | None
    role: Literal["stat", "sys", "total", "unspecified"]
    meaning: Literal[
        "standard_uncertainty",
        "expanded_uncertainty",
        "confidence_interval",
        "credible_interval",
        "quantile_bounds",
        "reported_error",
        "unspecified",
    ]
    interpretation_state: Literal["parsed", "unresolved"]
    reason: str | None
    source_unit: str | None = None
    relative_basis: Literal["reported_main_value", "unknown"] | None = None
    level_kind: (
        Literal[
            "confidence_probability",
            "credible_probability",
            "coverage_factor",
            "sigma_label",
            "quantile_levels",
        ]
        | None
    ) = None
    level_values: list[str] = Field(default_factory=list)
    level_raw_text: str | None = None
    semantics_evidence: list[Anchor] = Field(default_factory=list, max_length=4)
    semantic_support_fields: list[Literal["role", "meaning", "relative_basis"]] = Field(
        default_factory=list, max_length=3
    )
    catalog_semantics_evidence: list[CatalogSemanticAnchor] = Field(
        default_factory=list, max_length=6
    )

    @model_serializer(mode="wrap")
    def serialize_optional_semantic_support(self, handler):
        value = handler(self)
        if not self.semantic_support_fields:
            value.pop("semantic_support_fields", None)
        return value


class SourceQualityProposal(Contract):
    state: Literal["checked", "unresolved", "invalid"]
    raw_info: list[str]
    caution_quotes: list[str]
    note: str = Field(min_length=1)


class ConditionProposal(Contract):
    key: str
    state: Literal["known", "not_reported", "unresolved", "not_applicable"]

    @field_validator("state", mode="before")
    @classmethod
    def unresolved_spelling(cls, value):
        return "unresolved" if value == "unknown" else value

    value: str | bool | int | list[str] | dict[str, JsonValue] | None
    raw_text: str | None

    @field_validator("value", mode="before")
    @classmethod
    def numeric_context_literal(cls, value):
        if type(value) is float:
            from math import isfinite

            if not isfinite(value):
                raise ValueError("nonfinite context value")
            return repr(value)
        return value


class ReportedReferenceProposal(Contract):
    raw_code: str = Field(min_length=1)
    location: str = Field(min_length=1)
    role: Literal['adopted_measurement','method','background','comparison','unknown'] = 'unknown'
    link_quote: str | None = None
    page: int | None = None
    block_ids: list[str] = Field(default_factory=list, max_length=8)


class CatalogFieldRole(Contract):
    column: str
    role: Literal["uncertainty", "context", "reference", "quality", "limit"]
    source_quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    context_key: str | None = None


class MeasurementProposal(Contract):
    property_id: str
    value: ScientificValue
    raw_value: str
    unit: str | None
    representation: Literal[
        "linear", "log10", "ln", "magnitude", "category", "boolean", "text", "relation"
    ]
    source_quote: str
    page: int | None
    row: int | None
    column: str | None
    subject_role: Literal["target", "component", "member", "host", "other", "unresolved"]
    result_role: Literal[
        "reported_result",
        "adopted_measurement",
        "assumption",
        "calibration_constant",
        "rejected_solution",
        "unresolved",
    ]
    location_kind: Literal["body", "table", "caption", "plot", "catalog_cell"]
    limit: Literal["none", "upper", "lower", "upper_open", "lower_open"]
    errors: list[ErrorProposal]
    conditions: list[ConditionProposal]
    ambiguity: str | None
    representation_parameters: Representation | None = None
    location_label: str | None = None
    source_quality: SourceQualityProposal | None = None
    source_references: list[ReportedReferenceProposal] = Field(default_factory=list, max_length=32)
    citation_state: Literal['seen','not_seen','unknown'] = 'unknown'
    local_admission: AdmissionCheck | None = None
    quantity_match: Literal["exact", "different", "unresolved"] | None = None
    catalog_quantity_evidence: list[str] = Field(default_factory=list, max_length=8)
    catalog_field_roles: list[CatalogFieldRole] = Field(default_factory=list, max_length=24)
    catalog_review_issue: CatalogScientificIssue | None = None

    @model_serializer(mode="wrap")
    def serialize_optional_catalog_roles(self, handler):
        result = handler(self)
        if not self.catalog_field_roles:
            result.pop("catalog_field_roles", None)
        if self.catalog_review_issue is None:
            result.pop('catalog_review_issue', None)
        return result


class ContextRequest(Contract):
    page: int | None
    locator: str | None
    property_ids: list[str]
    reason: str


class ExtractionBatch(Contract):
    results: list[MeasurementProposal] = Field(max_length=24)
    coverage: Literal["checked", "partial", "unreadable"]
    limitations: list[str]
    context_requests: list[ContextRequest] = Field(default_factory=list, max_length=2)
    figures: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=12)
    figure_requests: list[int] = Field(default_factory=list, max_length=4)


def validated_batch(raw):
    """A malformed candidate/context request cannot erase independent valid items."""
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise DomainError("EXTRACTION_BATCH_SCHEMA", "提取结果必须含候选数组")
    batch = ExtractionBatch.model_validate({**raw, "results": [], "context_requests": [], 'figures':[], 'figure_requests':[]})
    malformed, results, requests = ([], [], [])

    def retain_failure(kind, index, item, error):
        malformed.append(
            {
                "kind": kind,
                "index": index,
                "raw_proposal": item,
                "errors": [
                    {key: detail[key] for key in ("loc", "type", "msg")}
                    for detail in error.errors(include_url=False)
                ],
            }
        )

    for index, item in enumerate(raw["results"]):
        if index >= 24:
            malformed.append(
                {
                    "kind": "result",
                    "index": index,
                    "raw_proposal": item,
                    "reason": "candidate_response_capacity",
                }
            )
            continue
        try:
            if isinstance(item,dict):
                item = dict(item)
                refs = item.get('source_references', [])
                good = []
                if not isinstance(refs,list):
                    refs = []
                    malformed.append({'kind':'source_reference','index':index,'reason':'reference_list_schema'})
                for ref in refs[:32]:
                    try:
                        good.append(ReportedReferenceProposal.model_validate(ref).model_dump(mode='json'))
                    except ValidationError:
                        malformed.append({'kind':'source_reference','index':index,'raw_reference':ref,'reason':'reference_item_schema'})
                item['source_references'] = good
                for key, model in [('local_admission',AdmissionCheck), ('source_quality',SourceQualityProposal)]:
                    if item.get(key) is not None:
                        try:
                            model.model_validate(item[key])
                        except ValidationError:
                            malformed.append({'kind':key,'index':index,'raw_annotation':item[key],
                                              'reason':'optional_reader_annotation_schema'})
                            item[key] = None
                if item.get('citation_state','unknown') not in {'seen','not_seen','unknown'}:
                    malformed.append({'kind':'citation_state','index':index,'reason':'citation_state_schema'})
                    item['citation_state'] = 'unknown'
            results.append(MeasurementProposal.model_validate(item))
        except ValidationError as exc:
            retain_failure("result", index, item, exc)
    raw_requests = raw.get("context_requests", [])
    if not isinstance(raw_requests, list):
        malformed.append(
            {
                "kind": "context_requests",
                "raw_proposal": raw_requests,
                "reason": "context_request_list_schema",
            }
        )
    else:
        for index, item in enumerate(raw_requests):
            if index >= 2:
                malformed.append(
                    {
                        "kind": "context_request",
                        "index": index,
                        "raw_proposal": item,
                        "reason": "context_request_capacity",
                    }
                )
                continue
            try:
                requests.append(ContextRequest.model_validate(item))
            except ValidationError as exc:
                retain_failure("context_request", index, item, exc)
    figure_hints, figure_requests = [], []
    for key, target, limit in [('figures',figure_hints,12), ('figure_requests',figure_requests,4)]:
        entries = raw.get(key, [])
        if not isinstance(entries,list):
            malformed.append({'kind':key,'reason':'invalid_figure_list'})
            continue
        for item in entries[:limit]:
            if key == 'figures' and isinstance(item,dict) or key == 'figure_requests' and type(item) is int:
                target.append(item)
            else:
                malformed.append({'kind':key,'reason':'invalid_figure_item'})
    return (
        batch.model_copy(
            update={
                "results": results,
                "context_requests": requests,
                'figures':figure_hints, 'figure_requests':figure_requests,
                "coverage": "partial" if any(m.get('kind') not in {'figures','figure_requests','source_reference','citation_state','local_admission','source_quality'} for m in malformed) else batch.coverage,
            }
        ),
        malformed,
    )


def evidence_ref(obj: dict, key: str):
    return {"id": obj[key], "version": obj.get("revision", 1), "content_sha256": content_hash(obj)}
