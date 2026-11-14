"""Explicitly synthetic fixtures made for the new protocols, never production."""

from copy import deepcopy

from astroquery_ai.runtime.codec import content_hash, digest


def ref(name="synthetic-ref"):
    return {"id": name, "version": 1, "content_sha256": digest({"synthetic": name})}


def error_component(
    component_id="synthetic-stat",
    kind="symmetric_delta",
    values=None,
    role="stat",
    meaning="reported_error",
):
    return {
        "component_id": component_id,
        "interpretation_state": "parsed",
        "kind": kind,
        "values": values if values is not None else {"delta": "0.1"},
        "role": role,
        "raw_label": role,
        "statistical_meaning": meaning,
        "level": None,
        "representation_ref": ref("source-space"),
        "unit_ref": ref("source-unit"),
        "basis_ref": None,
        "axes": [],
        "dependency_refs": [],
        "evidence_refs": [ref("evidence")],
        "raw_text": "SYNTHETIC reported uncertainty",
        "interpretation_provenance": ref("source-interpretation"),
        "reason": None,
    }


def measurement(
    mid="synthetic-measurement",
    pid="synthetic-property",
    source="synthetic-source",
    value="2",
    components=None,
):
    components = [] if components is None else components
    result = {
        "schema_version": "SourceMeasurement/2",
        "measurement_id": mid,
        "revision": 1,
        "task_id": "synthetic-task",
        "query_ref": ref("query"),
        "target_ref": ref("target"),
        "property_ref": ref(pid),
        "source_ref": ref(source),
        "interpretation_ref": ref("interpretation"),
        "source_kind": "paper",
        "value": {"kind": "real", "value": value},
        "raw_value": value,
        "unit": "m",
        "representation": "linear",
        "limit": "none",
        "uncertainty": {
            "contract_version": "UncertaintyBundle/1",
            "state": "reported" if components else "not_reported",
            "components": deepcopy(components),
            "raw_refs": [ref("raw")],
            "reason": None,
            "inspection_ref": ref("inspection"),
        },
        "context_ref": ref("context"),
        "evidence_refs": [ref("evidence")],
        "admission_receipt_ref": ref("admission"),
        "source_qualification_ref": ref("qualification"),
        "lineage_refs": [],
    }
    result["content_sha256"] = content_hash(result)
    return result


def derived(record, status="ready", main_state="ready"):
    return {
        "derived_id": "derived-" + record["measurement_id"],
        "measurement_id": record["measurement_id"],
        "status": status,
        "main_state": main_state,
        "value_typed": record["value"],
        "limit": record["limit"],
        "uncertainty_typed": {"components": []},
    }
