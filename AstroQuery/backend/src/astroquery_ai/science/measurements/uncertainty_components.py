"Preserve and construct independent reported uncertainty components."

from pydantic import ValidationError

from astroquery_ai.runtime.codec import digest

from astroquery_ai.runtime.models import UncertaintyComponent

from astroquery_ai.science.unit_declarations import catalog_unit_declaration

from .contracts import evidence_ref
from .uncertainty_values import canonical_error_values


def assemble_uncertainties(*, doc, source, owner, mid, evref, ur, ir, component_parent_ids, main_unit_declaration=None):
    components, component_units, bases = ([], [], [])
    identities=set()
    for ordinal,error in enumerate(doc["errors"]):
        parsed = error["interpretation_state"] == "parsed"
        if (
            error["kind"] in {"relative", "percent"}
            and error["relative_basis"] != "reported_main_value"
        ):
            parsed = False
        if error["kind"] in {"covariance", "correlation"}:
            parsed = False
        error_declaration = (
            catalog_unit_declaration(
                source, error["location"], proposed_unit=error["source_unit"] or doc["unit"]
            )
            if owner == "M03"
            else None
        )
        if (error_declaration is None and main_unit_declaration and error['source_unit'] is None
                and parsed and doc['representation']=='linear'
                and error['kind'] in {'symmetric_delta','asymmetric_delta','interval_endpoints'}):
            # An absolute error on the same reported coordinate shares its
            # evidenced unit, while the absent printed unit remains absent.
            error_declaration=dict(main_unit_declaration)
        if (
            error["kind"] in {"variance", "inverse_variance"}
            and error["source_unit"] is None
            and (error_declaration is None)
        ):
            parsed = False
        error_unit_text = error["source_unit"]
        if error_unit_text is None and parsed:
            error_unit_text = (
                "%"
                if error["kind"] == "percent"
                else "1"
                if error["kind"] == "relative"
                else {'log10':'dex','ln':'1','magnitude':'mag'}[doc['representation']]
                if doc['representation'] in {'log10','ln','magnitude'}
                and error['kind'] in {'symmetric_delta','asymmetric_delta','interval_endpoints'}
                else doc["unit"]
            )
        error_unit = {
            "unit_id": "error-unit-"
            + digest(
                {
                    "measurement": mid,
                    "location": error["location"],
                    "unit": error_unit_text,
                    "evidence": evref,
                }
            ),
            "unit_text": error_unit_text,
            "evidence_refs": [evref],
            **({'printed_unit_literal':None,'unit_origin':'reported_coordinate_coefficient'}
                if error['source_unit'] is None and parsed and doc['representation'] in {'log10','ln','magnitude'} else {}),
            **({"unit_declaration": error_declaration} if error_declaration else {}),
        }
        component_units.append(error_unit)
        basis_ref = None
        if parsed and error["kind"] in {"relative", "percent"}:
            basis = {
                "basis_id": "basis-"
                + digest(
                    {"measurement": mid, "location": error["location"], "value": doc["value"]}
                ),
                "kind": "source_declared_main_magnitude",
                "value": doc["value"].get("value"),
                "evidence_refs": [evref],
            }
            if basis["value"] is None:
                parsed = False
            else:
                bases.append(basis)
                basis_ref = evidence_ref(basis, "basis_id")
        level = None
        if error["level_kind"] is not None:
            if not error["level_values"] or not error["level_raw_text"]:
                parsed = False
            else:
                level = {
                    "kind": error["level_kind"],
                    "values": error["level_values"],
                    "raw_text": error["level_raw_text"],
                    "evidence_refs": [evref],
                }
        identity={'measurement':mid,'location':error['location'],'role':error['role'],
            **({'parent_component_id':component_parent_ids[error['location']]}
               if component_parent_ids and error['location'] in component_parent_ids else {})}
        if digest(identity) in identities:
            # Two independent errors may share a printed cell and an unknown
            # role. Keep both; location/role is not a unique component key.
            identity['source_component_ordinal']=ordinal
        identities.add(digest(identity))
        values, adaptation = canonical_error_values(error['kind'], error['values']) if parsed else (None, None)
        components.append(
            {
                "component_id": "component-"
                + digest(identity),
                "interpretation_state": "parsed" if parsed else "unresolved",
                "kind": error["kind"],
                "values": values,
                "role": error["role"],
                "raw_label": error["role"],
                "statistical_meaning": error["meaning"],
                "level": level,
                "representation_ref": ur,
                "unit_ref": evidence_ref(error_unit, "unit_id"),
                "basis_ref": basis_ref,
                "axes": [],
                "dependency_refs": [],
                "evidence_refs": [evref],
                "raw_text": error["raw_text"],
                "interpretation_provenance": ir,
                "reason": None
                if parsed
                else error["reason"] or "source_dependency_interpretation_required",
                **({'value_adaptation': adaptation} if adaptation else {}),
            }
        )
        try:
            UncertaintyComponent.model_validate(components[-1])
        except ValidationError:
            components[-1].update(
                interpretation_state="unresolved",
                values=None,
                level=None,
                reason="reported_component_schema_unresolved",
            )
    uncertainty_state = (
        "not_reported"
        if not components
        else "reported"
        if any((c["interpretation_state"] == "parsed" for c in components))
        else "unresolved"
    )
    return (components, component_units, bases, uncertainty_state)
