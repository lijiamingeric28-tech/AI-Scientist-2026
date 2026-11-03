"""Typed optional-error interpretation; does not import wire encoding."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from astroquery_ai.runtime.models import Contract, Delta, Sides, IntervalValue

from astroquery_ai.science.measurements.contracts import ErrorProposal


class InterpretedError(ErrorProposal):
    values: Delta | Sides | IntervalValue | None
    reason: str | None = None
    semantic_support: dict[Literal["role", "meaning", "relative_basis"], list[str]] = Field(
        default_factory=dict
    )


class ComponentInterpretation(Contract):
    source_component_id: str
    outcome: Literal["parsed", "needs_review", "unresolved"]
    errors: list[InterpretedError] = Field(default_factory=list, max_length=8)
    evidence_span_ids: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(min_length=1, max_length=1500)


class InterpretationBatch(Contract):
    measurement_id: str
    input_hash: str
    components: list[ComponentInterpretation] = Field(max_length=24)
