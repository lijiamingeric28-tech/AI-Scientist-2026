"Admission evidence protocol types and exact legacy hash compatibility."

from __future__ import annotations

import re

import unicodedata

from copy import deepcopy

from typing import Literal

from pydantic import Field, field_validator, model_serializer, model_validator, ValidationError

from astroquery_ai.runtime.codec import digest

from astroquery_ai.runtime.models import Contract


class Anchor(Contract):
    page: int = Field(ge=1)
    quote: str | None = Field(default=None, max_length=4000)
    block_ids: list[str] = Field(default_factory=list, max_length=6)


class LocalContext(Contract):
    kind: Literal[
        "method",
        "epoch",
        "band",
        "fiducial",
        "source_caution",
        "result_identity",
        "author_explanation",
    ]
    text: str = Field(min_length=1, max_length=1500)
    anchor: Anchor
    subject_scope: Literal["target", "all_reported_objects", "other", "unresolved"] | None = None
    property_scope: (
        Literal["selected_quantity", "all_source_quantities", "other", "unresolved"] | None
    ) = None


class SubjectLink(Contract):
    method: Literal["evidenced_alias", "table_scope", "section_scope", "cross_page_scope", "semantic_scope"]
    relation: Literal["target", "other", "unresolved"]
    local_evidence: list[Anchor] = Field(min_length=1, max_length=3)
    scope_evidence: list[Anchor] = Field(min_length=1, max_length=4)
    counter_evidence: list[Anchor] = Field(default_factory=list, max_length=3)
    reason: str = Field(min_length=1, max_length=2000)


class ReviewChoice(Contract):
    action: Literal['confirm','correct','not_supported','unable']
    label: str = Field(min_length=1,max_length=160)
    impact: str = Field(min_length=1,max_length=500)


class ScientificIssue(Contract):
    issue_kind: Literal['object_semantics','quantity_semantics','unit_semantics','condition_semantics']
    issue_key: str = Field(min_length=3,max_length=160)
    question: str = Field(min_length=8,max_length=1200)
    undecided_fact: str = Field(min_length=3,max_length=600)
    scope_evidence: list[Anchor] = Field(min_length=1,max_length=4)
    support_evidence: list[Anchor] = Field(min_length=1,max_length=4)
    counter_evidence: list[Anchor] = Field(default_factory=list,max_length=4)
    choices: list[ReviewChoice] = Field(min_length=2,max_length=3)
    correction_types: list[Literal['correct_value', 'correct_unit', 'correct_uncertainty', 'correct_context']] = Field(default_factory=list, max_length=4)


class CatalogScientificIssue(Contract):
    issue_kind: Literal['object_semantics', 'quantity_semantics', 'unit_semantics', 'condition_semantics']
    issue_key: str = Field(min_length=3, max_length=160)
    question: str = Field(min_length=8, max_length=1200)
    undecided_fact: str = Field(min_length=3, max_length=600)
    scope_kind: Literal['matched_row','column_definition'] = 'matched_row'
    scope_columns: list[str] = Field(min_length=1, max_length=8)
    support_columns: list[str] = Field(min_length=1, max_length=8)
    counter_columns: list[str] = Field(default_factory=list, max_length=8)
    choices: list[ReviewChoice] = Field(min_length=2, max_length=3)
    correction_types: list[Literal['correct_value', 'correct_unit', 'correct_uncertainty', 'correct_context']] = Field(default_factory=list, max_length=4)


def canonical_quantity_relation(value):
    """Wire synonyms keep their negative/unknown meaning, never grant admission."""
    return {'different': 'related_or_different', 'unknown': 'insufficient'}.get(value, value) if isinstance(value, str) else value


class EstimatorIdentity(Contract):
    selected_requirement: str = Field(min_length=1,max_length=400)
    reported_estimator: str = Field(min_length=1,max_length=600)
    relation: Literal['same','different','insufficient','not_restricted']
    evidence: list[Anchor] = Field(default_factory=list,max_length=4)

    @model_validator(mode='after')
    def grounded_estimator(self):
        if self.relation in {'same','different'} and not self.evidence:
            raise ValueError('estimator relation requires actual source evidence')
        return self


class QuantityIdentity(Contract):
    reported_quantity: str = Field(min_length=1,max_length=600)
    subject_scale: str = Field(min_length=1,max_length=300)
    native_representation: str = Field(min_length=1,max_length=300)
    native_coordinate_kind: Literal['linear','log10','ln','magnitude','category','boolean','text','relation'] | None = Field(
        default=None, description='Mathematical native coordinate of the original reported quantity/coefficient, not decimal typography; establish from actual source quantity definition/header.')
    relation: Literal['same','related_or_different','requires_derivation','insufficient']
    evidence: list[Anchor] = Field(min_length=1,max_length=4)
    estimator_identity: EstimatorIdentity | None = None

    @model_validator(mode='after')
    def consistent_estimator(self):
        method=self.estimator_identity
        if method and self.relation=='same' and method.relation in {'different','insufficient'}:
            raise ValueError('same quantity contradicts unresolved/different defining estimator')
        return self

    @model_serializer(mode='wrap')
    def serialize_optional_estimator(self,handler):
        value=handler(self)
        if self.estimator_identity is None:value.pop('estimator_identity',None)
        if self.native_coordinate_kind is None:value.pop('native_coordinate_kind',None)
        return value

    @field_validator('relation', mode='before')
    @classmethod
    def relation_spelling(cls, value):
        return canonical_quantity_relation(value)


class DefiningEstimator(Contract):
    requirement: Literal['required','not_restricted','insufficient'] = Field(
        description='Does the selected exact definition AND confirmed request require a particular estimator? A general quantity does not require one merely because the source uses a method.')
    selected_requirement: str | None = Field(default=None,max_length=600,
        description='The specific defining estimator/method required by the exact selected name/definition or confirmed wording. Null when not_restricted; do not repeat the general physical quantity or its unit/coordinate as an estimator.')
    reported_estimator: str = Field(min_length=1,max_length=600)
    match: Literal['same','different','insufficient'] | None = Field(default=None,
        description='Compare the actual source method only when requirement=required; otherwise null. A comparison with a named estimator does not mean the result used it.')
    evidence: list[Anchor] = Field(default_factory=list,max_length=4)

    @model_validator(mode='after')
    def consistent_requirement(self):
        if self.requirement=='required':
            if not self.selected_requirement or not self.selected_requirement.strip():
                raise ValueError('required estimator must name the actual defining method from the selected scope')
            if self.match is None:raise ValueError('required estimator needs an explicit source-method comparison')
            if self.match in {'same','different'} and not self.evidence:
                raise ValueError('estimator match/difference requires source evidence')
        elif self.match is not None:
            raise ValueError('unrestricted/unknown requirement must not assert a defining-method match')
        if self.requirement=='not_restricted' and self.selected_requirement is not None:
            raise ValueError('not_restricted has no defining estimator: selected_requirement must be null, with the actual source method retained separately')
        return self


class QuantityScope(Contract):
    reported_quantity: str = Field(min_length=1,max_length=600)
    subject_scale: str = Field(min_length=1,max_length=300)
    native_representation: str = Field(min_length=1,max_length=300)
    native_coordinate_kind: Literal['linear','log10','ln','magnitude','category','boolean','text','relation']
    physical_relation: Literal['same','related_or_different','requires_derivation','insufficient'] = Field(
        description='Relation of the actual source quantity to the selected physical quantity, before checking a defining estimator. Same dimensions are not enough.')
    evidence: list[Anchor] = Field(min_length=1,max_length=4)
    estimator: DefiningEstimator

    def identity(self):
        """Generate compatibility verdicts from one structured decision, never prose."""
        relation=self.physical_relation
        method=self.estimator
        if relation=='same':
            if method.requirement=='insufficient':relation='insufficient'
            elif method.requirement=='required':
                relation={'same':'same','different':'related_or_different','insufficient':'insufficient'}[method.match]
        estimator_relation=(method.match if method.requirement=='required' else
                            'not_restricted' if method.requirement=='not_restricted' else 'insufficient')
        return QuantityIdentity(reported_quantity=self.reported_quantity,subject_scale=self.subject_scale,
            native_representation=self.native_representation,native_coordinate_kind=self.native_coordinate_kind,
            relation=relation,evidence=self.evidence,estimator_identity=EstimatorIdentity(
                selected_requirement=method.selected_requirement or ('No defining estimator in selected scope' if method.requirement=='not_restricted' else 'Defining estimator requirement unresolved'),reported_estimator=method.reported_estimator,
                relation=estimator_relation,evidence=method.evidence))


class AdmissionCheck(Contract):
    index: int = Field(ge=0, le=23)
    subject: Literal["target", "other", "unresolved"]
    printed_subject: str | None
    subject_evidence: list[Anchor] = Field(max_length=4)
    result_role: Literal[
        "reported_result",
        "adopted_measurement",
        "assumption",
        "calibration_constant",
        "rejected_solution",
        "not_reported",
        "unresolved",
    ]
    role_evidence: list[Anchor] = Field(max_length=4)
    context: list[LocalContext] = Field(default_factory=list, max_length=8)
    reason: str = Field(min_length=1, max_length=2000)
    quantity_match: Literal["exact", "different", "unresolved"] | None = None
    quantity_identity: QuantityIdentity | None = None
    quantity_evidence: list[Anchor] = Field(default_factory=list, max_length=4)
    subject_link: SubjectLink | None = None
    value_location_kind: Literal["body", "table", "caption", "plot", "unresolved"] | None = None
    review_issue: ScientificIssue | None = None
    unit_match: Literal['exact', 'different', 'unresolved', 'not_applicable'] | None = None
    native_unit: str | None = None
    unit_evidence: list[Anchor] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def consistent_quantity_identity(self):
        if self.quantity_identity is not None:
            expected={'same':'exact','related_or_different':'different',
                      'requires_derivation':'different','insufficient':'unresolved'}[self.quantity_identity.relation]
            if self.quantity_match!=expected:
                raise ValueError('quantity_identity.relation contradicts quantity_match')
        return self

    @model_serializer(mode="wrap")
    def serialize_optional_layout(self, handler):
        value = handler(self)
        if self.value_location_kind is None:
            value.pop("value_location_kind", None)
        if self.review_issue is None:
            value.pop('review_issue',None)
        if self.quantity_identity is None:
            value.pop('quantity_identity',None)
        if self.unit_match is None:
            for key in ('unit_match', 'native_unit', 'unit_evidence'):
                value.pop(key, None)
        return value


class AdmissionChecks(Contract):
    results: list[AdmissionCheck] = Field(max_length=24)


def admission_outcome(response):
    """Keep valid siblings; malformed/duplicate checks are never decisions."""
    valid, errors, seen = {}, [], set()
    rows = response.get('results') if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) > 24:
        return {}, [{'reason': 'admission_batch_schema'}]
    for ordinal, raw in enumerate(rows):
        try:
            check = AdmissionCheck.model_validate(raw)
            if check.index in seen:
                valid.pop(check.index, None)
                errors.append({'index': check.index, 'reason': 'duplicate_check'})
                continue
            seen.add(check.index)
            valid[check.index] = check
        except ValidationError as exc:
            errors.append({'ordinal': ordinal, 'reason': 'admission_item_schema',
                           'fields': [{'loc': list(e['loc']), 'type': e['type']} for e in exc.errors()]})
    return valid, errors


class AdmissionLocatorCheck(Contract):
    index: int = Field(ge=0, le=23)
    subject: Literal["target", "other", "unresolved"]
    printed_subject: str | None
    subject_evidence: list[Anchor] = Field(max_length=4)
    subject_link: SubjectLink


class AdmissionLocatorChecks(Contract):
    results: list[AdmissionLocatorCheck] = Field(max_length=24)


def normalized(text):
    return re.sub("\\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def matches_proposal_hash(document, expected):
    if digest(document) == expected:
        return True
    legacy = deepcopy(document)
    if legacy.get("quantity_match") is None:
        legacy.pop("quantity_match", None)
    if not legacy.get("catalog_quantity_evidence"):
        legacy.pop("catalog_quantity_evidence", None)
    for context in (legacy.get("local_admission") or {}).get("context", []):
        for key in ("subject_scope", "property_scope"):
            if context.get(key) is None:
                context.pop(key, None)
    if (legacy.get("local_admission") or {}).get("subject_link") is None:
        (legacy.get("local_admission") or {}).pop("subject_link", None)
    return digest(legacy) == expected
