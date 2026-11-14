"""Library conversion permission precedes models and independent arithmetic."""
from .unit_declarations import execution_unit, output_coordinate_unit


def conversion_permission(policy, record, output, source_representation, *, scientific_permission=None):
    if scientific_permission is not None:
        # This receipt is built by M08 from exact science and local software
        # checks, never from the author's historical runtime flags.
        return scientific_permission
    numeric = record["value"]["kind"] in {"real", "integer", "interval"}
    if numeric and policy.get("numeric_paths_state") in {
        "not_published",
        "disabled",
        "unvalidated",
    }:
        return {"allowed": False, "reason": "numeric_execution_not_published"}
    if numeric and source_representation is None:
        return {"allowed": False, "reason": "source_representation_parameters_unresolved"}
    target_unit = output_coordinate_unit(output)
    from astroquery_ai.registry.models import Representation

    identical = (
        execution_unit(record) == target_unit
        and source_representation == Representation.model_validate(output["representation"])
        if numeric
        else record["representation"] == output["representation"]["kind"]
    )
    if "allowed_transforms" in policy:
        transforms = policy["allowed_transforms"]
        if identical and "identity" in transforms:
            return {"allowed": True, "reason": "approved_identity"}
        return {"allowed": False, "reason": "transform_not_explicitly_published"}
    operators = policy.get("allowed_operators", [])
    required = (
        {source_representation.kind, output["representation"]["kind"]}
        if numeric
        else {record["representation"]}
    )
    return {
        "allowed": bool(required) and required <= set(operators),
        "reason": "declared_representation_operators"
        if required <= set(operators)
        else "representation_operator_not_approved",
    }


def not_run_representation(record, output, reason):
    from astroquery_ai.runtime.codec import digest

    return {
        "schema_version": "DerivedRepresentation/2",
        "derived_id": "not-run-"
        + digest(
            {
                "source": record["content_sha256"],
                "profile": output["content_sha256"],
                "reason": reason,
            }
        ),
        "measurement_id": record["measurement_id"],
        "source_representation_hash": record["content_sha256"],
        "output_profile_ref": {
            "id": output["profile_id"],
            "version": output["version"],
            "content_sha256": output["content_sha256"],
        },
        "status": "not_run",
        "main_state": "not_run",
        "value_typed": None,
        "uncertainty_typed": None,
        "limit": record["limit"],
        "issues": [{"code": reason}],
        "method": "original_source_retained",
        "conversion_policy_ref": output["conversion_policy_ref"],
    }
