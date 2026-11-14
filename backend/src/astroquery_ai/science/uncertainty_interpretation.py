"Evidence-bound optional-error interpretation, separate from numerical conversion.\n\nNothing in this protocol can change the main measurement or grant a conversion.\nThe source producer's existing admission and uncertainty validators are reused.\n"

from __future__ import annotations

from astroquery_ai.science.measurements.uncertainty_contracts import (
    ComponentInterpretation,
    InterpretationBatch,
    InterpretedError,
)

from astroquery_ai.science.measurements.uncertainty_validation import (
    _numbers,
    grounded_numbers,
    validate_proposal,
)

from copy import deepcopy

from decimal import Decimal, InvalidOperation

import re

from typing import Literal

from pydantic import Field, ValidationError

from astroquery_ai.runtime.codec import digest, loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import Contract, UncertaintyComponent, Delta, Sides, IntervalValue

from astroquery_ai.science.measurements.contracts import ErrorProposal, MeasurementProposal

from astroquery_ai.science.measurements.admission_contracts import Anchor, normalized

from astroquery_ai.science.paper_admission import preserve_uncertainty_semantics

VERSION = "source-error-interpretation-6"

OPERATION = "error_interpretation"


def available_spans(evidence, interpretation, source=None):
    """Use carried cells/metadata and already checked paper anchors; no PDF reread.

    An unverified reader transcription never becomes independent source evidence.
    The origin remains explicit, including model-grounded source anchors.
    """
    items = []
    if evidence.get("text_origin") == "original_cells":
        try:
            saved = loads(evidence["raw_text"])
        except (ValueError, TypeError):
            saved = None
        if isinstance(saved, dict):
            proposal = interpretation["proposal"]
            cells = saved.get("cells") or {}
            local_columns = {
                proposal.get("column"),
                *(
                    e["location"] if e["location"] in cells else e["location"].split("/")[0]
                    for e in proposal["errors"]
                ),
                *(r["location"] for r in proposal.get("source_references", [])),
            }
            local_columns.discard(None)
            for name, value in (saved.get("cells") or {}).items():
                if name in local_columns and isinstance(value, str) and value.strip():
                    items.append({"locator": name, "text": value, "origin": "original_cell"})
            for column in saved.get("columns") or []:
                if isinstance(column, dict) and column.get("name") in local_columns:
                    items.append(
                        {
                            "locator": column.get("name"),
                            "text": str(column),
                            "column_metadata": column,
                            "origin": "original_column_metadata",
                        }
                    )
            for key in ("description", "notes"):
                text = ((source or {}).get("metadata") or {}).get(key)
                if isinstance(text, str) and text.strip():
                    items.append(
                        {"locator": "table_" + key, "text": text, "origin": "original_table_note"}
                    )
            document = ((source or {}).get("metadata") or {}).get("catalog_document")
            if document and document.get("artifact_ref"):
                from astroquery_ai.science.catalog_document import document_view

                view = document_view(
                    document, local_columns, [c["name"] for c in saved.get("columns", [])]
                )
                snippets = [span for group in view["field_descriptions"].values() for span in group]
                snippets += [span for group in view["notes"].values() for span in group]
                if view.get("catalog_scope"):
                    snippets.append(view["catalog_scope"])
                for snippet in snippets:
                    items.append(
                        {
                            "locator": {
                                "line_start": snippet["line_start"],
                                "line_end": snippet["line_end"],
                                **({'text_view':view['text_view']} if view.get('text_view') else {}),
                            },
                            "text": snippet["text"],
                            "artifact_ref": document["artifact_ref"],
                            "origin": "carried_catalog_document",
                        }
                    )
    verification = interpretation.get("paper_verification") or {}
    if verification.get("state") == "passed":
        for block in verification.get("source_information_blocks", []):
            items.append(
                {
                    "locator": block["block_id"],
                    "page": block["page"],
                    "text": block["text"],
                    "origin": "checked_source_information_block",
                }
            )
        check = verification.get("check") or {}
        anchors = [
            a
            for key in ("subject_evidence", "role_evidence", "quantity_evidence", "unit_evidence")
            for a in check.get(key, [])
        ]
        anchors.extend(
            (
                a
                for key in ("local_evidence", "scope_evidence", "counter_evidence")
                for a in (check.get("subject_link") or {}).get(key, [])
            )
        )
        anchors.extend(
            (item["anchor"] for item in verification.get("context", []) if item.get("anchor"))
        )
        for anchor in anchors:
            if anchor.get("quote"):
                items.append(
                    {
                        "locator": {"page": anchor["page"]},
                        "page": anchor["page"],
                        "text": anchor["quote"],
                        "origin": "checked_paper_anchor",
                    }
                )
    unique = {}
    for item in items:
        key = "error-span-" + digest(item)
        unique[key] = {"span_id": key, **item}
    return list(unique.values())


def prompt(record, interpretation, spans, *, component_ids=None):
    from astroquery_ai.science.uncertainty_wire import compact_prompt

    return compact_prompt(record, interpretation, spans, VERSION, component_ids=component_ids)


def validate_response(raw, record, interpretation, spans, *, component_ids=None):
    from astroquery_ai.science.uncertainty_wire import expand_response

    expanded = expand_response(raw, record, interpretation, spans, component_ids=component_ids)
    binding = expanded.pop("_source_binding")
    proposal, outcomes, parents = validate_proposal(
        expanded, record, interpretation, spans, component_ids=component_ids
    )
    for outcome in outcomes:
        outcome.update(binding.get(outcome["source_component_id"], {}))
    return (proposal, outcomes, parents)
