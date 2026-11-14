"""New synthetic release with review/hash dependencies; never a scientific DB."""

import hashlib
from pathlib import Path

from astroquery_ai.registry.compiler import compile_rules
from astroquery_ai.runtime.codec import canonical, content_hash, digest


def make_release(path: Path, *, dimensionless=False, native_only_policy=False):
    path.mkdir(parents=True)
    reviews = []

    def ref(obj, key):
        return {
            "id": obj[key],
            "version": obj.get("version", obj.get("definition_version", 1)),
            "content_sha256": obj["content_sha256"],
        }

    def reviewed(obj, key):
        review = {
            "review_id": "review-" + obj[key],
            "version": 1,
            "reviewed_payload_sha256": digest(obj),
            "decision": "approved",
            "reviewer_kind": "synthetic_fixture",
            "checks": {"synthetic_expected_structure": "passed"},
            "synthetic": True,
        }
        review["content_sha256"] = content_hash(review)
        reviews.append(review)
        obj["review_ref"] = ref(review, "review_id")
        obj["content_sha256"] = content_hash(obj)
        return obj

    evidence = {
        "evidence_id": "synthetic-evidence",
        "version": 1,
        "text": "SYNTHETIC unit/definition example; not a scientific assertion",
        "synthetic": True,
    }
    evidence["content_sha256"] = content_hash(evidence)
    ev = ref(evidence, "evidence_id")
    family = reviewed(
        {
            "family_id": "synthetic-family",
            "version": 1,
            "description": "Synthetic family",
            "member_property_ids": ["synthetic-length"],
            "search_concepts": ["synthetic length"],
            "evidence_refs": [ev],
        },
        "family_id",
    )
    subject = reviewed(
        {
            "subject_class_id": "synthetic-subject",
            "version": 1,
            "description": "Synthetic whole subject",
            "evidence_refs": [ev],
        },
        "subject_class_id",
    )
    scale = reviewed(
        {
            "object_scale_id": "synthetic-whole",
            "version": 1,
            "description": "Synthetic fixed object scale",
            "evidence_refs": [ev],
        },
        "object_scale_id",
    )
    policy = reviewed(
        {
            "policy_id": "synthetic-same-length",
            "version": 1,
            **({'allowed_transforms': ['identity', 'affine'], 'numeric_paths_state': 'not_published',
                'description': 'SYNTHETIC source-specific scientific conditions; no generic execution authority'}
               if native_only_policy else {'allowed_operators': ['linear', 'log10']}),
            "evidence_refs": [ev],
        },
        "policy_id",
    )
    definition = reviewed(
        {
            "property_id": "synthetic-length",
            "definition_version": 1,
            "name_cn": "合成测试无量纲比值" if dimensionless else "合成测试整体长度",
            "name_en": "Synthetic dimensionless ratio" if dimensionless else "Synthetic whole length",
            "aliases": ["测试长度"],
            "description": "SYNTHETIC fixture: a dimensionless ratio already reported by a source" if dimensionless else "SYNTHETIC fixture: a length already reported by a source",
            "distinction_notes": ["Not a production scientific property"],
            "quantity_key": "synthetic:whole_ratio" if dimensionless else "synthetic:whole_length",
            "quantity_kind": "ratio" if dimensionless else "length",
            "scientific_purpose": "Software test only",
            "subject_class_id": "synthetic-subject",
            "scope": "whole_object",
            "definition_qualifiers": {},
            "measurement_conditions_schema": [],
            "value_schema": {"kind": "real"},
            "family_id": "synthetic-family",
            "ucd": {"state": "not_assigned", "reason": "synthetic test"},
            "evidence_refs": [ev],
            "explanation": {
                "subject": "合成主体",
                "quantity": "已报告无量纲比值" if dimensionless else "已报告整体长度",
                "boundary": "整体",
                "representation": "无量纲" if dimensionless else "米",
                "distinctions": ["不代表真实科学库"],
                "evidence_scope": "仅测试夹具",
            },
        },
        "property_id",
    )
    profile = reviewed(
        {
            "profile_id": "synthetic-metre",
            "version": 1,
            "property_id": "synthetic-length",
            "definition_version": 1,
            "object_scale_id": "synthetic-whole",
            "unit": {'kind': 'dimensionless', 'canonical_symbol': '1', 'semantic_kind': 'synthetic_ratio'} if dimensionless else {
                "kind": "physical",
                "canonical_symbol": "m",
                "dimension": "length",
                "parser_format": "generic",
                "parser_version": "astropy-test",
            },
            "representation": {"kind": "linear"},
            "conversion_policy_ref": ref(policy, "policy_id"),
        },
        "profile_id",
    )
    rules = [
        reviewed(
            {
                "rule_id": "synthetic-rule-" + str(i),
                "version": 1,
                "condition": {"all_of": [{"otype": code}, {"subject_class": "synthetic-subject"}]},
                "definition_ref": ref(definition, "property_id"),
                "profile_ref": ref(profile, "profile_id"),
                "evidence_refs": [ev],
                "display_order": 0,
                "enabled": True,
            },
            "rule_id",
        )
        for i, code in enumerate(["*", "pA*"])
    ]
    composition = {"rules": rules, "exclusions": []}
    data = {
        "taxonomy": {
            "nodes": [
                {"otype": code, "section_number": 1, "status": "current"} for code in ["*", "pA*"]
            ],
            "in_scope_codes": ["*", "pA*"],
            "candidate_codes": ["pA*?"],
        },
        "definitions": [definition],
        "output-profiles": [profile],
        "conversion-policies": [policy],
        "subject-classes": [subject],
        "object-scales": [scale],
        "type-profiles": [
            {"otype": code, "subject_class_id": "synthetic-subject", "coverage_gap_refs": []}
            for code in ["*", "pA*"]
        ],
        "composition": composition,
        "families": [family],
        "evidence": [evidence],
        "reviews": reviews,
        "coverage": {"types": ["*", "pA*"]},
        "gaps": [],
        "compiled-support": compile_rules(rules, []),
        "test-vectors": [
            {
                "id": "single",
                "otypes": ["*"],
                "subject_class_id": "synthetic-subject",
                "expected_property_ids": ["synthetic-length"],
            },
            {
                "id": "union",
                "otypes": ["pA*", "*"],
                "subject_class_id": "synthetic-subject",
                "expected_property_ids": ["synthetic-length"],
            },
        ],
    }
    files = []
    for role, value in data.items():
        raw = canonical(value)
        name = role + ".json"
        (path / name).write_bytes(raw)
        files.append({"path": name, "role": role, "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schema_version": "property-registry/1",
        "release_id": "synthetic-registry-v1",
        "status": "ready_to_import",
        "synthetic": True,
        "content_files": files,
    }
    manifest["content_sha256"] = content_hash(manifest)
    (path / "manifest.json").write_bytes(canonical(manifest))
    return data
