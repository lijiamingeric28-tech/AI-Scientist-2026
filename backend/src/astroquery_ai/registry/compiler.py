"""Finite declarative conditions. No eval, taxonomy inheritance or model calls."""

from __future__ import annotations
from itertools import product

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError


def condition_variables(condition: dict, depth=0) -> set[str]:
    if depth > 16 or not isinstance(condition, dict) or len(condition) != 1:
        raise DomainError("INVALID_COMPOSITION", "组合条件格式或深度无效", 422)
    op, value = next(iter(condition.items()))
    if op in {"otype", "subject_class"}:
        if not isinstance(value, str) or not value:
            raise DomainError("INVALID_COMPOSITION", "组合条件缺少标识", 422)
        return {f"{op}:{value}"}
    if op == "not":
        return condition_variables(value, depth + 1)
    if op in {"all_of", "any_of"} and isinstance(value, list) and value:
        return set().union(*(condition_variables(child, depth + 1) for child in value))
    raise DomainError("UNKNOWN_COMPOSITION_OPERATOR", "不允许的组合运算", 422)


def matches(condition: dict, types: set[str], subject_class: str) -> bool:
    condition_variables(condition)

    def check(node):
        op, value = next(iter(node.items()))
        if op == "otype":
            return value in types
        if op == "subject_class":
            return value == subject_class
        if op == "not":
            return not check(value)
        if op == "all_of":
            return all(check(child) for child in value)
        return any(check(child) for child in value)

    return check(condition)


def overlap_witness(first: dict, second: dict, exclusions: list[dict]) -> dict | None:
    variables = sorted(set().union(*(condition_variables(c) for c in [first, second, *exclusions])))
    # Fail closed for an excessive rule; never call an incomplete check "passed".
    if len(variables) > 18:
        raise DomainError("COMPOSITION_CHECK_LIMIT", "组合规则超过当前可完整核验的范围", 422)
    for values in product((False, True), repeat=len(variables)):
        assignment = {key for key, value in zip(variables, values) if value}
        subjects = [v.split(":", 1)[1] for v in assignment if v.startswith("subject_class:")]
        if len(subjects) > 1:
            continue
        types = {v.split(":", 1)[1] for v in assignment if v.startswith("otype:")}
        subject = subjects[0] if subjects else "__unassigned__"
        if (
            matches(first, types, subject)
            and matches(second, types, subject)
            and not any(matches(c, types, subject) for c in exclusions)
        ):
            return {"otypes": sorted(types), "subject_class": subject}
    return None


def compile_rules(rules: list[dict], exclusions: list[dict]) -> dict:
    allowed = {
        "rule_id",
        "version",
        "content_sha256",
        "condition",
        "definition_ref",
        "profile_ref",
        "evidence_refs",
        "review_ref",
        "display_order",
        "enabled",
    }
    seen = set()
    enabled = []
    for rule in rules:
        if set(rule) - allowed or not allowed - {"display_order"} <= set(rule):
            raise DomainError("INVALID_RULE_SCHEMA", "适用规则字段不完整或含执行扩展", 422)
        if rule["rule_id"] in seen:
            raise DomainError("DUPLICATE_RULE", "规则ID重复", 422)
        seen.add(rule["rule_id"])
        condition_variables(rule["condition"])
        if rule["enabled"] is True:
            enabled.append(rule)
        elif rule["enabled"] is not False:
            raise DomainError("INVALID_RULE_SCHEMA", "enabled必须为布尔值", 422)
    comparisons = 0
    for i, first in enumerate(enabled):
        for second in enabled[i + 1 :]:
            if first["definition_ref"]["id"] != second["definition_ref"]["id"]:
                continue
            if (
                first["profile_ref"] == second["profile_ref"]
                and first["definition_ref"] == second["definition_ref"]
            ):
                continue
            comparisons += 1
            witness = overlap_witness(first["condition"], second["condition"], exclusions)
            if witness:
                raise DomainError(
                    "UNRESOLVED_COMPOSITION",
                    "同一适用上下文存在多个输出配置；须在发布规则中消除重叠",
                    422,
                    rules=[first["rule_id"], second["rule_id"]],
                    witness=witness,
                )
    ordered = sorted(enabled, key=lambda r: r["rule_id"])
    return {
        "compiler_version": "declarative-1",
        "rules": ordered,
        "exclusions": exclusions,
        "checks": {
            "rule_count": len(rules),
            "profile_overlap_checks": comparisons,
            "status": "passed",
        },
        "content_sha256": digest({"rules": ordered, "exclusions": exclusions}),
    }
