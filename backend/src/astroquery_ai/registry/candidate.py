"""Dot candidate protocol reader. Verification never activates a runtime release."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from astroquery_ai.runtime.codec import content_hash, loads, digest
from astroquery_ai.runtime.errors import DomainError
from .compiler import matches


def local_file(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise DomainError("CANDIDATE_PATH", "候选包路径无效", 422)
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts:
        raise DomainError("CANDIDATE_PATH", "候选包路径越界", 422)
    path = (root.resolve() / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise DomainError("CANDIDATE_PATH", "候选包引用逃出暂存目录", 422)
    if os.name == "nt" and len(str(path)) >= 240 and not str(path).startswith("\\\\?\\"):
        path = Path("\\\\?\\" + str(path))
    if not path.is_file():
        raise DomainError("CANDIDATE_FILE_MISSING", "候选包引用文件缺失", 422, relative=relative)
    return path


def load_record(path):
    value = loads(path.read_bytes())

    def check(item):
        if type(item) is float or type(item) is int and abs(item) > 9007199254740991:
            raise DomainError("CANDIDATE_CANONICAL_NUMBER", "PR-C14N/1禁止浮点和非安全整数", 422)
        if isinstance(item, dict):
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)

    check(value)
    return value


def _reference_identity(ref):
    """The exact identity used by reference_key, without serializing it again."""
    return ref['id'], str(ref['version']), ref['content_sha256']


@dataclass(frozen=True)
class _SelectionIndexes:
    definitions: object
    profiles: object
    rules_by_group: object
    tables_by_subject: object
    rule_profiles: object
    declared_profiles: object


def _selection_indexes(release):
    from .amendments import reference_key

    data = release['data']
    definitions = {_reference_identity({'id': item['property_id'],
        'version': item['definition_version'], 'content_sha256': item['content_sha256']}): item
        for item in data['definitions']}
    profiles = {_reference_identity({'id': item['profile_id'],
        'version': item['version'], 'content_sha256': item['content_sha256']}): item
        for item in data['output_profiles']}
    aliases = release.get('reference_aliases', {})
    rules_by_group, rule_profiles = defaultdict(list), {}
    for rule in data['unapproved_aggregate_composition_and_rules']['rules']:
        rules_by_group[(rule['definition_ref']['id'], rule['subject_class_id'])].append(rule)
        key = reference_key(rule['profile_ref']) if aliases else None
        resolved = aliases.get(key, rule['profile_ref'])
        rule_profiles[id(rule)] = resolved, digest(resolved), key in aliases
    tables_by_subject, declared_profiles = defaultdict(list), {}
    for table in data['build_only_symbolic_support']['tables']:
        nodes = MappingProxyType({node['id']: node for node in table['nodes']})
        tables_by_subject[table['subject_class_id']].append((table, nodes))
        for partition in table['partitions']:
            declared_profiles[id(partition)] = frozenset(digest(ref) for ref in partition['candidate_profile_refs'])
    return _SelectionIndexes(
        MappingProxyType(definitions), MappingProxyType(profiles),
        MappingProxyType({key: tuple(value) for key, value in rules_by_group.items()}),
        MappingProxyType({key: tuple(value) for key, value in tables_by_subject.items()}),
        MappingProxyType(rule_profiles), MappingProxyType(declared_profiles))


class CandidateRegistry:
    def __init__(self, release=None):
        """Optionally prepare indexes for one immutable compilation input.

        Unprepared readers continue to observe each supplied source anew. The
        prepared indexes live only on this reader, never on a returned release.
        """
        self._prepared_release = release
        self._indexes = _selection_indexes(release) if release is not None else None

    def select_context(self, release, *, accepted_otypes, subject_class_id):
        """Read declared symbolic outcomes and independently compare source ASTs.

        Accepted target assertions remain the caller's responsibility. This
        candidate result grants no production/model/source execution permission.
        """
        types = set(accepted_otypes)
        indexes = self._indexes if release is self._prepared_release else _selection_indexes(release)
        bindings, gaps = [], []
        for table, nodes in indexes.tables_by_subject.get(subject_class_id, ()):

            def evaluate(root):
                seen = set()
                while root not in {0, 1}:
                    if root in seen or root not in nodes:
                        raise DomainError("CANDIDATE_BDD_STRUCTURE", "候选决策图有环或缺节点", 422)
                    seen.add(root)
                    node = nodes[root]
                    index = node["variable_index"]
                    if type(index) is not int or not 0 <= index < len(table["variables"]):
                        raise DomainError("CANDIDATE_BDD_VARIABLE", "候选决策变量无效", 422)
                    root = node["high"] if table["variables"][index] in types else node["low"]
                return root == 1

            partitions = [item for item in table["partitions"] if evaluate(item["root"])]
            if len(partitions) != 1:
                raise DomainError("CANDIDATE_PARTITION", "当前上下文没有唯一决策分区", 422)
            partition = partitions[0]
            active = [
                rule
                for rule in indexes.rules_by_group.get((table['property_id'],subject_class_id), ())
                if matches(rule["when"], types, subject_class_id)
            ]
            if any(rule["kind"] != "include" for rule in active):
                raise DomainError("CANDIDATE_RULE_DIALECT", "此版本消费者尚未支持该规则类别", 422)
            independently_selected = {indexes.rule_profiles[id(rule)][1] for rule in active}
            declared = indexes.declared_profiles[id(partition)]
            if independently_selected != declared:
                raise DomainError(
                    "CANDIDATE_SYMBOLIC_AST_MISMATCH", "决策产物与原规则在当前上下文不一致", 422
                )
            expected = (
                "no_active" if not declared else "resolved" if len(declared) == 1 else "conflict"
            )
            if partition["outcome"] != expected:
                raise DomainError("CANDIDATE_OUTCOME_MISMATCH", "原规则与产物结论不一致", 422)
            if expected != "resolved":
                if expected == "conflict":
                    gaps.append(
                        {
                            "property_id": table["property_id"],
                            "reason": "unresolved_output_profile_conflict",
                        }
                    )
                continue
            reference = partition["winner_profile_ref"]
            profile = indexes.profiles.get(_reference_identity(reference))
            definition_refs={_reference_identity(r['definition_ref']):r['definition_ref'] for r in active
                if indexes.rule_profiles[id(r)][0]==reference}
            if len(definition_refs)>1:
                gaps.append({'property_id':table['property_id'],'reason':'reviewed_definition_versions_conflict',
                    'definition_refs':list(definition_refs.values()),'no_version_chosen':True})
                continue
            definition=indexes.definitions.get(next(iter(definition_refs))) if len(definition_refs)==1 else None
            if (
                not profile
                or not definition
                or profile["content_sha256"] != reference["content_sha256"]
                or profile["version"] != reference["version"]
            ):
                raise DomainError("CANDIDATE_BINDING_REFERENCE", "符号绑定引用不可核验", 422)
            bindings.append(
                {
                    "schema_version": "candidate-scientific-binding/1",
                    "definition": definition,
                    "output_profile": profile,
                    "active_rule_refs": [rule["rule_id"] for rule in active],
                    "source_package_manifest_hash": release["report"]["manifest_content_sha256"],
                    "current_context_ast_agrees": True,
                    **({'reference_alignment_ref':release['reference_alignment_ref']} if any(
                        indexes.rule_profiles[id(rule)][2] for rule in active) else {}),
                    "runtime_authorized": False,
                }
            )
        return {
            "schema_version": "candidate-support/1",
            "accepted_otypes": sorted(types),
            "subject_class_id": subject_class_id,
            "bindings": bindings,
            "gaps": gaps,
            "runtime_authorized": False,
            "scientific_profile_validated": False,
        }

    def inspect(self, package: Path, supplement: Path | None = None):
        package = package.resolve()
        handoff = load_record(local_file(package, "registry-handoff.json"))
        if (
            handoff.get("format") != "registry-candidate-handoff/1"
            or handoff.get("active") is not False
            or handoff.get("ready_to_import") is not False
        ):
            raise DomainError("CANDIDATE_PROTOCOL", "候选包协议或状态不符", 422)
        manifest_path = local_file(package, handoff["manifest_path"])
        manifest_raw = manifest_path.read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != handoff["manifest_file_sha256"]:
            raise DomainError("CANDIDATE_MANIFEST_HASH", "候选主清单原字节哈希不一致", 422)
        manifest = load_record(manifest_path)
        if manifest["content_sha256"] != content_hash(manifest):
            raise DomainError("CANDIDATE_CONTENT_HASH", "候选清单规范载荷哈希不一致", 422)
        paths, verified_bytes = set(), 0
        for record in manifest["content_files"]:
            if record["path"] in paths:
                raise DomainError("CANDIDATE_DUPLICATE_FILE", "候选清单路径重复", 422)
            paths.add(record["path"])
            path = local_file(package, record["path"])
            if path.stat().st_size != record["bytes"]:
                raise DomainError(
                    "CANDIDATE_FILE_HASH", "候选文件长度不一致", 422, relative=record["path"]
                )
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024**2), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != record["file_sha256"]:
                raise DomainError(
                    "CANDIDATE_FILE_HASH", "候选文件哈希不一致", 422, relative=record["path"]
                )
            verified_bytes += record["bytes"]
        data = {}
        for item in manifest["data_files"]:
            if item["path"] not in paths or item["role"] in data:
                raise DomainError("CANDIDATE_DATA_INDEX", "候选数据角色未被清单唯一固定", 422)
            data[item["role"]] = load_record(local_file(package, item["path"]))
        review_index = {(r["review_id"], r["version"]): r for r in data["reviews"]}
        identities = {
            "definitions": "property_id",
            "output_profiles": "profile_id",
            "subject_classes": "subject_class_id",
            "object_scales": "object_scale_id",
            "conversion_policies": "policy_id",
            "families": "family_id",
            "evidence": "evidence_id",
            "quantity_schemas": "quantity_schema_id",
        }
        reviewed, pending = [], []
        for role, key in identities.items():
            for record in data.get(role, []):
                if record["content_sha256"] != content_hash(record):
                    raise DomainError(
                        "CANDIDATE_OBJECT_HASH",
                        "科学对象规范哈希不一致",
                        422,
                        role=role,
                        object_id=record[key],
                    )
                reference = record.get("review_ref")
                if not reference:
                    continue
                review = review_index.get((reference["review_id"], reference["version"]))
                valid = (
                    review
                    and review.get("candidate_content_hash") == record["content_sha256"]
                    and review.get("candidate_ref", {}).get("id") == record[key]
                )
                if valid and review["content_sha256"] != content_hash(review):
                    raise DomainError("CANDIDATE_REVIEW_HASH", "候选审核回执哈希不一致", 422)
                (reviewed if valid and review["decision"] == "approved" else pending).append(
                    {
                        "role": role,
                        "id": record[key],
                        "version": record.get("definition_version", record.get("version")),
                        "review_id": reference["review_id"],
                    }
                )
        report = {
            "schema_version": "candidate-consumer-inspection/1",
            "package_id": handoff["package_id"],
            "manifest_file_sha256": handoff["manifest_file_sha256"],
            "manifest_content_sha256": manifest["content_sha256"],
            "verified_files": len(paths),
            "verified_bytes": verified_bytes,
            "data_counts": {
                role: len(value) for role, value in data.items() if isinstance(value, list)
            },
            "current_approved_review_refs": reviewed,
            "pending_or_stale_review_refs": pending,
            "compiled_support_format": handoff["compiled_support_format"],
            "consumer_adaptation": "pending",
            "scientific_profile_validated": False,
            "runtime_authorized": False,
            "active": False,
            "source_candidate_state_preserved": True,
        }
        if supplement is not None:
            report["source_matrix"] = self.inspect_matrix(
                package, manifest, data, supplement.resolve()
            )
        return {"report": report, "handoff": handoff, "manifest": manifest, "data": data}

    def inspect_matrix(self, package, manifest, data, supplement):
        listing = loads(local_file(supplement, "supplement-manifest.json").read_bytes())
        for item in listing["files"]:
            raw = local_file(supplement, item["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise DomainError(
                    "CANDIDATE_SUPPLEMENT_HASH",
                    "来源测试补充文件哈希不一致",
                    422,
                    relative=item["path"],
                )
        matrix = loads(
            local_file(
                supplement, "recovery03/psr/delivery_test_v2/five-target-matrix.json"
            ).read_bytes()
        )
        definitions = {d["property_id"]: d for d in data["definitions"]}
        mismatches = []
        for item in matrix["properties"]:
            actual = definitions.get(item["property_id"])
            expected = item["definition_ref"]
            if (
                not actual
                or actual["content_sha256"] != expected["content_sha256"]
                or actual["definition_version"] != expected["version"]
            ):
                mismatches.append(item["property_id"])
        pin = matrix["final_selector_binding"]
        matching = [
            item for item in manifest["content_files"] if item["file_sha256"] == pin["sha256"]
        ]
        selector_verified = bool(matching)
        return {
            "format": matrix["record_type"],
            "targets": len(matrix["targets"]),
            "properties": len(matrix["properties"]),
            "cells": len(matrix["cells"]),
            "definition_mismatches": mismatches,
            "selector_pin_verified": selector_verified,
            "selector_pin": pin,
            "selector_gap": None
            if selector_verified
            else "原始选择器精确文件哈希未出现在主包清单；未替换为其他selector冒充通过",
            "matrix_content_sha256": digest(matrix),
            "matrix_file_sha256": hashlib.sha256(
                local_file(
                    supplement, "recovery03/psr/delivery_test_v2/five-target-matrix.json"
                ).read_bytes()
            ).hexdigest(),
            "source_cell_counts": {
                state: sum(cell["status"] == state for cell in matrix["cells"])
                for state in ("expected", "missing", "conditional")
            },
            "runtime_accepted": False,
            "M08_accepted": False,
        }
