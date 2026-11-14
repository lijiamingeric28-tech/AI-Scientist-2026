"""Evidence and arithmetic checks for interpreted errors, independent of the wire protocol."""

from __future__ import annotations

from copy import deepcopy

from decimal import Decimal, InvalidOperation

import re

from pydantic import ValidationError

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import UncertaintyComponent

from astroquery_ai.science.measurements.contracts import ErrorProposal, MeasurementProposal

from astroquery_ai.science.measurements.admission_contracts import Anchor, normalized

from astroquery_ai.science.paper_admission import preserve_uncertainty_semantics

from astroquery_ai.science.measurements.uncertainty_contracts import (
    ComponentInterpretation,
    InterpretationBatch,
)


def _numbers(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"kind", "lower_closed", "upper_closed"}:
                yield from _numbers(item)


def grounded_numbers(error, parent_raw):
    """Independent literal/last-digit arithmetic; never accept model rounding."""
    raw = error.raw_text.replace("−", "-").replace("–", "-")
    literals = [
        Decimal(m) for m in re.findall("[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?", raw)
    ]
    signed = error.kind == "interval_endpoints"
    allowed = set(literals if signed else [abs(n) for n in literals])
    notation = re.fullmatch(
        "\\s*([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))\\((\\d+)\\)([eE][+-]?\\d+)?\\s*", parent_raw
    )
    if notation and error.kind == "symmetric_delta":
        mantissa, digits, exponent = notation.groups()
        places = len(mantissa.split(".")[1]) if "." in mantissa else 0
        allowed = {Decimal(digits) * Decimal(10) ** (int((exponent or "e0")[1:]) - places)}
    try:
        return bool(error.values) and all(
            (Decimal(n).is_finite() and Decimal(n) in allowed for n in _numbers(error.values))
        )
    except (InvalidOperation, TypeError):
        return False


def validate_proposal(raw, record, interpretation, spans, *, component_ids=None):
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("components"), list)
        or len(raw["components"]) > 24
    ):
        raise DomainError("ERROR_INTERPRETATION_SCHEMA", "误差解释响应必须含组件数组")
    batch = InterpretationBatch.model_validate({**raw, "components": []})
    if (
        batch.measurement_id != record["measurement_id"]
        or batch.input_hash != record["content_sha256"]
    ):
        raise DomainError("ERROR_INTERPRETATION_SCOPE", "误差解释响应与当前测量不一致")
    proposal = deepcopy(interpretation["proposal"])
    original = proposal["errors"]
    components = record["uncertainty"]["components"]
    if len(original) != len(components):
        raise DomainError("ERROR_INTERPRETATION_SOURCE_LAYOUT", "原报误差与组件对应关系不完整")
    if component_ids is not None and (
        not set(component_ids) <= {c["component_id"] for c in components}
    ):
        raise DomainError("ERROR_INTERPRETATION_SCOPE", "请求含其他测量的误差组件")
    requested = {
        c["component_id"]: (i, c)
        for i, c in enumerate(components)
        if (
            c["interpretation_state"] == "unresolved"
            if component_ids is None
            else c["component_id"] in component_ids
        )
    }
    ids = [
        item.get("source_component_id") if isinstance(item, dict) else None
        for item in raw["components"]
    ]
    if (
        not all((isinstance(key, str) for key in ids))
        or len(ids) != len(set(ids))
        or set(ids) != set(requested)
    ):
        raise DomainError("ERROR_INTERPRETATION_COVERAGE", "响应须完整保留每个请求组件身份")
    span_index = {s["span_id"]: s for s in spans}
    replacements, outcomes, parents = ({}, [], {})
    for document in raw["components"]:
        try:
            item = ComponentInterpretation.model_validate(document)
        except ValidationError:
            outcomes.append(
                {
                    "source_component_id": document["source_component_id"],
                    "outcome": "unresolved",
                    "reason": "component_response_schema",
                    "evidence_span_ids": [],
                }
            )
            continue
        index, component = requested[item.source_component_id]
        source_error = original[index]
        selected = [span_index[key] for key in item.evidence_span_ids if key in span_index]
        outcome = {
            "source_component_id": item.source_component_id,
            "outcome": item.outcome,
            "reason": item.reason,
            "evidence_span_ids": item.evidence_span_ids,
        }
        outcomes.append(outcome)

        def fail(reason):
            outcome.update(outcome="unresolved", validation_reason=reason)

        if item.outcome not in {"parsed", "needs_review", "unresolved"} or len(selected) != len(
            item.evidence_span_ids
        ):
            fail("invalid_outcome_or_evidence_id")
            continue
        parent_literal = any(
            (normalized(component["raw_text"]) in normalized(s["text"]) for s in selected)
        )
        if not selected or not parent_literal:
            fail("original_error_not_in_carried_evidence")
            continue
        if item.outcome != "parsed":
            if item.errors:
                fail("unresolved_outcome_cannot_replace_source")
            continue
        if not item.errors:
            fail("parsed_without_components")
            continue
        checked = []
        for structured in item.errors:
            error = ErrorProposal.model_validate(
                structured.model_dump(mode="json", exclude={"semantic_support"})
            )
            supports = structured.semantic_support
            if any(
                (
                    not ids or not set(ids) <= set(item.evidence_span_ids)
                    for ids in supports.values()
                )
            ):
                fail("semantic_support_not_bound_to_component_evidence")
                break
            if (
                component["interpretation_state"] == "parsed"
                and component["kind"] == "asymmetric_delta"
                and (sum((v is not None for v in component["values"].values())) == 1)
                and (error.kind == "symmetric_delta")
            ):
                fail("one_sided_uncertainty_cannot_become_symmetric")
                break
            if (
                error.interpretation_state != "parsed"
                or not error.raw_text
                or normalized(error.raw_text) not in normalized(component["raw_text"])
                or (error.location != source_error["location"])
                or (error.kind in {"covariance", "correlation", "other_reported"})
                or (not grounded_numbers(error, component["raw_text"]))
            ):
                fail("component_numbers_location_or_kind_not_supported")
                break
            if error.source_unit is not None:
                if not any(
                    (
                        s.get("column_metadata", {}).get("unit_text") == error.source_unit
                        and s["locator"] == source_error["location"]
                        or (
                            s["origin"] != "original_column_metadata"
                            and re.search(
                                "(?<!\\w)" + re.escape(error.source_unit) + "(?!\\w)", s["text"]
                            )
                        )
                        for s in selected
                    )
                ):
                    fail("unit_not_in_source_evidence")
                    break
            elif error.kind in {"variance", "inverse_variance"}:
                fail("variance_source_unit_required")
                break
            if error.role != "unspecified" and "role" not in supports:
                words = {
                    "stat": "\\bstat(?:istical)?\\b|统计",
                    "sys": "\\bsys(?:tematic)?\\b|系统",
                    "total": "\\btotal\\b|总误差|总不确定",
                }
                own_label = re.search(words[error.role], error.raw_text, re.I)
                column_label = any(
                    (
                        s["origin"] == "original_column_metadata"
                        and s["locator"] == source_error["location"]
                        and re.search(
                            words[error.role],
                            re.sub(
                                "\\bstat\\.error(?:\\.[\\w-]+)*\\b", "ucd-error-field", s["text"]
                            ),
                            re.I,
                        )
                        and (
                            not any(
                                (
                                    re.search(
                                        pattern,
                                        re.sub(
                                            "\\bstat\\.error(?:\\.[\\w-]+)*\\b",
                                            "ucd-error-field",
                                            s["text"],
                                        ),
                                        re.I,
                                    )
                                    for role, pattern in words.items()
                                    if role != error.role
                                )
                            )
                        )
                        for s in selected
                    )
                )
                if (
                    not own_label
                    and (not column_label)
                    and (
                        len(
                            [
                                role
                                for role, pattern in words.items()
                                if any(
                                    (
                                        re.search(
                                            pattern,
                                            re.sub(
                                                "\\bstat\\.error(?:\\.[\\w-]+)*\\b",
                                                "ucd-error-field",
                                                s["text"],
                                            ),
                                            re.I,
                                        )
                                        for s in selected
                                    )
                                )
                            ]
                        )
                        > 1
                    )
                ):
                    fail("component_role_association_ambiguous")
                    break
            if error.kind in {"relative", "percent"} and (
                error.relative_basis != "reported_main_value"
                or (
                    "relative_basis" not in supports
                    and (
                        not any(
                            (
                                re.search(
                                    "relative to|fractional|percentage of|percent of|主值|分母",
                                    s["text"],
                                    re.I,
                                )
                                for s in selected
                            )
                        )
                    )
                )
            ):
                fail("relative_basis_not_declared")
                break
            if error.level_kind:
                if not error.level_raw_text or not any(
                    (normalized(error.level_raw_text) in normalized(s["text"]) for s in selected)
                ):
                    fail("level_not_in_source_evidence")
                    break
                level_numbers = {
                    abs(Decimal(n)) for n in re.findall("\\d+(?:\\.\\d+)?", error.level_raw_text)
                }
                if "%" in error.level_raw_text:
                    level_numbers |= {n / 100 for n in level_numbers}
                if not error.level_values or any(
                    (Decimal(n) not in level_numbers for n in error.level_values)
                ):
                    fail("level_number_not_in_source_evidence")
                    break
            pages = {
                p: "\n".join(
                    (
                        re.sub("\\bstat\\.error(?:\\.[\\w-]+)*\\b", "ucd-error-field", s["text"])
                        for s in selected
                        if s.get("page", 1) == p
                    )
                )
                for p in {s.get("page", 1) for s in selected}
            }
            anchors = []
            for page in sorted(pages):
                pending = ""
                for span in (s for s in selected if s.get("page", 1) == page):
                    if len(span["text"]) > 4000:
                        anchors = []
                        break
                    combined = pending + ("\n" if pending else "") + span["text"]
                    if len(combined) > 4000:
                        anchors.append(Anchor(page=page, quote=pending))
                        pending = span["text"]
                    else:
                        pending = combined
                else:
                    if pending:
                        anchors.append(Anchor(page=page, quote=pending))
                    continue
                break
            if not anchors or len(anchors) > 4:
                fail("complete_semantic_evidence_exceeds_anchor_profile")
                break
            error = error.model_copy(update={"semantics_evidence": anchors})
            legacy = preserve_uncertainty_semantics(
                MeasurementProposal.model_validate(
                    {**proposal, "errors": [error.model_dump(mode="json")]}
                ),
                pages,
                [{"page": p, "block_id": str(p), "text": text} for p, text in pages.items()],
            ).errors[0]
            if (
                "role" not in supports
                and legacy.role != error.role
                or (error.level_kind and legacy.level_kind != error.level_kind)
            ):
                fail("semantic_label_not_supported")
                break
            if "meaning" not in supports and legacy.meaning != error.meaning:
                outcome.setdefault("discarded_unsubstantiated_labels", []).append(
                    {
                        "field": "meaning",
                        "proposed": error.meaning,
                        "retained": "reported_error",
                        "reason": "not_established_by_carried_source_evidence",
                    }
                )
                error = error.model_copy(update={"meaning": "reported_error"})
            outcome["semantic_basis"] = {
                "kind": "source_component_model_interpretation",
                "source_component_id": item.source_component_id,
                "evidence_span_ids": item.evidence_span_ids,
                "reason": item.reason,
                "semantic_support": supports,
                "literal_keyword_required": not bool(supports),
            }
            try:
                UncertaintyComponent.model_validate(
                    {
                        **component,
                        "interpretation_state": "parsed",
                        "kind": error.kind,
                        "values": error.values,
                        "role": error.role,
                        "statistical_meaning": error.meaning,
                        "basis_ref": component["unit_ref"]
                        if error.kind in {"relative", "percent"}
                        else None,
                        "raw_text": error.raw_text,
                        "reason": None,
                        "level": {
                            "kind": error.level_kind,
                            "values": error.level_values,
                            "raw_text": error.level_raw_text,
                            "evidence_refs": component["evidence_refs"],
                        }
                        if error.level_kind
                        else None,
                    }
                )
            except ValueError:
                fail("component_numeric_or_level_schema_invalid")
                break
            checked.append(error.model_dump(mode="json"))
        if len(checked) != len(item.errors):
            continue
        if not any((part.semantic_support for part in item.errors)):
            role_words = {
                "stat": "\\bstat(?:istical)?\\b|统计",
                "sys": "\\bsys(?:tematic)?\\b|系统",
                "total": "\\btotal\\b|总误差|总不确定",
            }
            declared_roles = {
                role
                for role, pattern in role_words.items()
                if re.search(pattern, component["raw_text"], re.I)
            }
            if len(declared_roles) > 1 and (not declared_roles <= {e["role"] for e in checked}):
                fail("reported_component_role_lost")
                continue
        if len(checked) == 1:
            checked[0]["raw_text"] = component["raw_text"]
        if len(checked) > 1:
            roles = [e["role"] for e in checked]
            fragments = [normalized(e["raw_text"]) for e in checked]
            if (
                "unspecified" in roles
                or len(roles) != len(set(roles))
                or len(fragments) != len(set(fragments))
                or (normalized(component["raw_text"]) in fragments)
            ):
                fail("split_roles_not_distinct")
                continue
            for error in checked:
                error["location"] = source_error["location"] + "/" + error["role"]
        for error in checked:
            parents[error["location"]] = item.source_component_id
        replacements[index] = checked
    proposal["errors"] = [
        error for index, old in enumerate(original) for error in replacements.get(index, [old])
    ]
    return (MeasurementProposal.model_validate(proposal), outcomes, parents)
