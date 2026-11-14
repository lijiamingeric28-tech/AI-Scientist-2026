"""Versioned source identity/eligibility receipts, distinct from measurement merit."""

from astroquery_ai.runtime.codec import content_hash, digest


def qualify_source(source, *, identity, checked_scope, version_state="not_applicable"):
    # Eligibility does not certify every result in a source. Individual result
    # roles, quality flags and uncertainty meanings remain extraction checks.
    receipt = {
        "qualification_id": "qualification-"
        + digest({"source": source["source_id"], "identity": identity, "scope": checked_scope}),
        "schema_version": "SourceQualification/1",
        "source_id": source["source_id"],
        "state": "eligible",
        "identity": identity,
        "checked_scope": checked_scope,
        "version_state": version_state,
        "limitations": ["ordinary_errata_not_read", "measurement_validity_checked_separately"],
    }
    reference = {
        "id": receipt["qualification_id"],
        "version": 1,
        "content_sha256": content_hash(receipt),
    }
    return {**source, "qualification_ref": reference}, receipt
