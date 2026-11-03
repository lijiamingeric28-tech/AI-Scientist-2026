"""Explicit, hashed candidate-to-consumer views. This is never a release approval."""

from copy import deepcopy

from pydantic import ValidationError

from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from .models import PropertyDefinition, OutputProfile


def definition_view(registry, property_id, version, expected_hash):
    from .amendments import reference_key
    key=reference_key({'id':property_id,'version':version,'content_sha256':expected_hash})
    if registry.get('definition_views') is not None:return registry['definition_views'].get(key)
    value=registry.get('definitions',{}).get(property_id)
    return value if value and value.definition_version==version and value.content_sha256==expected_hash else None


def output_profile_view(registry, ref):
    from .amendments import reference_key
    if registry.get('profile_views') is not None:return registry['profile_views'].get(reference_key(ref))
    value=registry.get('profiles',{}).get(ref['id'])
    return value if value and value.version==ref['version'] and value.content_sha256==ref['content_sha256'] else None


def positive_version(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    raise DomainError("CANDIDATE_VERSION", "候选版本不是正整数标识", 422)


class CandidateProjection:
    """Source records/reviews stay byte-identical; projected views have their own hash."""

    version = "candidate-consumer-projection/1"

    def __init__(self, release):
        self.release = release
        self.science = release.get("science", {}).get("records", {})
        if self.science:
            self.version = "candidate-consumer-projection/3"
        self.reviews = {
            (item["review_id"], str(item["version"])): item for item in release["data"]["reviews"]
        }

    def reference(self, value):
        if isinstance(value, list):
            return [self.reference(item) for item in value]
        if not isinstance(value, dict):
            return value
        if {"id", "version", "content_sha256"} <= value.keys():
            return {
                "id": value["id"],
                "version": positive_version(value["version"]),
                "content_sha256": value["content_sha256"],
            }
        if set(value) == {"review_id", "version"}:
            review = self.reviews.get((value["review_id"], str(value["version"])))
            if not review or review["content_sha256"] != content_hash(review):
                raise DomainError("CANDIDATE_REVIEW_REFERENCE", "原始审查对象不可核验", 422)
            return {
                "id": review["review_id"],
                "version": positive_version(review["version"]),
                "content_sha256": review["content_sha256"],
            }
        return {key: self.reference(item) for key, item in value.items()}

    def definition(self, source, source_profile=None):
        view = self.reference(deepcopy(source))
        view["definition_version"] = positive_version(view["definition_version"])
        distinctions = view["explanation"]["distinctions"]
        if isinstance(distinctions, str):
            view["explanation"]["distinctions"] = [distinctions]
        conditions = []
        for item in source["measurement_conditions_schema"]:
            missing = item["missing_handling"]
            policies = {
                "cannot_bind_quantity": "block_admission",
                "cannot_compare": "limit_comparison",
                "optional": "optional",
                "retain_unknown": "retain_unknown",
            }
            if missing not in policies:
                raise DomainError(
                    "CANDIDATE_CONDITION_POLICY",
                    "未支持的条件缺失规则须保留缺口",
                    422,
                    policy=missing,
                )
            value_type = item["value_type"]
            if value_type == "category" or value_type == "text" and item.get("allowed_values"):
                value_type = "enum"
            candidates=self.release.get('science',{}).get('variants',{}).get(source['property_id'])
            source_records=[v['record'] for v in candidates if source_profile is None or v['record']['profile_ref']['content_sha256']==source_profile['content_sha256']] if candidates else [self.science.get(source['property_id'],{})]
            scopes={c.get('required_scope',item.get('required_scope','all_sources')) for record in source_records
                    for c in record.get('context_contracts',[]) if c['key']==item['key']}
            scope=next(iter(scopes)) if len(scopes)==1 else item.get('required_scope','all_sources')
            conditions.append(
                {
                    "key": item["key"],
                    "value_type": value_type,
                    # V4 gates main/error operations using their own predicates.
                    # The original definition and its older global flags remain
                    # intact in origin; this view must not preempt those gates.
                    "required_for_identity": not self.science and missing == "cannot_bind_quantity" and scope == "all_sources",
                    "required_for_comparison": missing == "cannot_compare" if self.science else bool(item["required"]),
                    "allowed_values": item.get("allowed_values", []),
                    "missing_policy": "retain_unknown" if self.science and missing == "cannot_bind_quantity" else policies[missing],
                    "required_scope": scope,
                }
            )
        view["measurement_conditions_schema"] = conditions
        view = PropertyDefinition.model_validate(view).model_dump(mode="json")
        if not self.science:
            for condition in view["measurement_conditions_schema"]:
                condition.pop("required_scope", None)
        view["content_sha256"] = content_hash(view)
        return view

    def profile(self, source):
        view = self.reference(deepcopy(source))
        for key in ("version", "definition_version"):
            view[key] = positive_version(view[key])
        if view["unit"].get("parser_format"):
            view["unit"]["parser_format"] = view["unit"]["parser_format"].lower()
            if view['unit']['parser_format'] == 'source_explicit_symbol_with_unremoved_h':
                view['unit']['parser_format'] = 'source_literal'
        rep = source["representation"]
        view["representation"] = {"kind": rep["kind"]}
        if rep["kind"] == "linear":
            if "multiplier" not in rep or "offset" not in rep:
                raise DomainError(
                    "CANDIDATE_LINEAR_PARAMETERS", "来源线性参数缺失，不自动补齐科学定义", 422
                )
            view["representation"].update(scale=rep["multiplier"], offset=rep["offset"])
        elif rep["kind"] in {"log10", "ln", "magnitude"}:
            if not all(rep.get(k) is not None for k in ('reference_value', 'reference_unit')):
                view['representation']['native_coordinate_only'] = True
            for key in ("scale", "offset", "reference_value", "reference_unit", "system_ref", "evidence_refs"):
                if key in rep:
                    value = rep[key]
                    if key == 'reference_unit' and isinstance(value, dict):
                        value = '1' if value.get('kind') == 'dimensionless' else value.get('canonical_symbol')
                        if not isinstance(value, str) or not value:
                            raise DomainError('CANDIDATE_REPRESENTATION_REFERENCE', '引用单位未明确给出规范符号', 422)
                    view["representation"][key] = self.reference(value)
            if rep['kind'] == 'magnitude' and rep.get('system_ref') is None:
                view['representation']['native_coordinate_only'] = True
        view = OutputProfile.model_validate(view).model_dump(mode="json")
        view["content_sha256"] = content_hash(view)
        return view

    def binding(self, binding):
        source_definition, source_profile = binding["definition"], binding["output_profile"]
        definition, profile = self.definition(source_definition,source_profile), self.profile(source_profile)
        policy = next(
            (
                item
                for item in self.release["data"]["conversion_policies"]
                if item['policy_id']==source_profile['conversion_policy_ref']['id']
                and str(item['version'])==str(source_profile['conversion_policy_ref']['version'])
                and item['content_sha256']==source_profile['conversion_policy_ref']['content_sha256']
            ),
            None,
        )
        if (
            not policy
            or policy["content_sha256"] != source_profile["conversion_policy_ref"]["content_sha256"]
        ):
            raise DomainError("CANDIDATE_CONVERSION_POLICY", "数值策略未固定到原始对象", 422)
        receipt = {
            "schema_version": self.version,
            "source_package_manifest_hash": binding["source_package_manifest_hash"],
            "source_definition_ref": {
                "id": source_definition["property_id"],
                "version": source_definition["definition_version"],
                "content_sha256": source_definition["content_sha256"],
            },
            "source_profile_ref": {
                "id": source_profile["profile_id"],
                "version": source_profile["version"],
                "content_sha256": source_profile["content_sha256"],
            },
            "definition_view_hash": definition["content_sha256"],
            "profile_view_hash": profile["content_sha256"],
            "original_records_and_scientific_reviews_retained": True,
            **({'reference_alignment_ref':binding['reference_alignment_ref']} if binding.get('reference_alignment_ref') else {}),
            "runtime_authorized": False,
            "aggregate_approval_granted": False,
            "scientific_profile_validated": False,
            "numeric_execution_granted": False,
        }
        receipt["receipt_id"] = "projection-" + digest(receipt)
        return {
            "property_id": definition["property_id"],
            "definition": definition,
            "output_profile": profile,
            "projection_receipt": receipt,
            "source_binding": binding,
            "source_conversion_policy": policy,
        }

    def support(self, support):
        bindings, gaps = [], list(support["gaps"])
        for binding in support["bindings"]:
            try:
                bindings.append(self.binding(binding))
            except (DomainError, ValidationError) as exc:
                gaps.append(
                    {
                        "property_id": binding["definition"]["property_id"],
                        "reason": getattr(exc, "code", "CANDIDATE_VIEW_SCHEMA"),
                        "details": exc.errors(include_url=False)
                        if isinstance(exc, ValidationError)
                        else exc.details,
                    }
                )
        return {
            "schema_version": self.version,
            "otypes": support["accepted_otypes"],
            "subject_class_id": support["subject_class_id"],
            "bindings": bindings,
            "gaps": gaps,
            "runtime_authorized": False,
            "active": False,
        }
