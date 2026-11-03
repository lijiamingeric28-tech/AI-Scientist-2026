"""Safe immutable release import and frozen-version deterministic consumers."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from pathlib import Path

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, new_id, utcnow
from astroquery_ai.runtime.errors import DomainError
from .compiler import compile_rules, matches
from .models import PropertyBinding, PropertyDefinition, OutputProfile

FILES = {
    "taxonomy",
    "definitions",
    "output-profiles",
    "conversion-policies",
    "subject-classes",
    "object-scales",
    "type-profiles",
    "composition",
    "families",
    "evidence",
    "reviews",
    "coverage",
    "gaps",
    "compiled-support",
    "test-vectors",
}


class RegistryService:
    def __init__(self, root: Path, repository, *, allow_synthetic=False):
        self.root, self.repository, self.allow_synthetic = (
            root.resolve(),
            repository,
            allow_synthetic,
        )
        self._consumer_cache = {}
        self._validation_lock = threading.RLock()

    @staticmethod
    def _file(root: Path, name: str) -> Path:
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
            raise DomainError("CORRUPT_RELEASE", "发布文件缺失或路径不合法", 422, file=name)
        return path

    def validate(self, directory: Path) -> dict:
        try:
            with self._validation_lock:
                return self._validate(directory)
        except DomainError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise DomainError("REGISTRY_SCHEMA", "性质库字段、引用或文件不可核验", 422) from exc

    def _validate(self, directory: Path) -> dict:
        directory = directory.resolve()
        manifest = loads(self._file(directory, "manifest.json").read_bytes())
        if manifest.get("schema_version") == "registry-candidate-consumer/1":
            return self._validate_consumer(directory, manifest)
        if manifest.get("schema_version") != "property-registry/1" or not manifest.get(
            "release_id"
        ):
            raise DomainError("REGISTRY_SCHEMA", "性质库发布协议不兼容", 422)
        if content_hash(manifest) != manifest.get("content_sha256"):
            raise DomainError("MANIFEST_HASH", "发布清单哈希不匹配", 422)
        if manifest.get("status") != "ready_to_import":
            raise DomainError("REGISTRY_NOT_APPROVED", "此包尚未完成发布审定", 422)
        synthetic = manifest.get("synthetic", False)
        if type(synthetic) is not bool or synthetic and not self.allow_synthetic:
            raise DomainError("SYNTHETIC_RELEASE", "合成测试库不能用于正式运行", 422)
        contents = manifest.get("content_files")
        if not isinstance(contents, list) or not contents:
            raise DomainError("CORRUPT_RELEASE", "发布清单缺少文件表", 422)
        data, seen = {}, set()
        for entry in contents:
            name, role = entry["path"], entry["role"]
            if name == "manifest.json" or name in seen or role in data:
                raise DomainError("DUPLICATE_RELEASE_FILE", "清单文件或角色重复", 422)
            seen.add(name)
            raw = self._file(directory, name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise DomainError("RELEASE_FILE_HASH", "发布文件哈希不匹配", 422, file=name)
            data[role] = loads(raw)
        if FILES - data.keys():
            raise DomainError(
                "CORRUPT_RELEASE", "性质库缺少强制角色", 422, missing=sorted(FILES - data.keys())
            )
        for role in FILES - {"composition", "compiled-support", "coverage", "taxonomy"}:
            if not isinstance(data[role], list):
                raise DomainError("REGISTRY_SCHEMA", "发布对象集合必须为数组", 422, role=role)
        taxonomy = data["taxonomy"]
        if (
            not isinstance(taxonomy, dict)
            or not isinstance(taxonomy.get("nodes"), list)
            or not taxonomy.get("nodes")
        ):
            raise DomainError("TAXONOMY_MISSING", "缺少来源分类快照", 422)
        scope = {
            node["otype"]
            for node in taxonomy["nodes"]
            if node.get("section_number") in {1, 2, 4, 5} and node.get("status") != "old"
        }
        if scope != set(taxonomy.get("in_scope_codes", [])) or not scope:
            raise DomainError("TAXONOMY_SCOPE", "产品分类范围与官方栏目节点不一致", 422)
        if {p.get("otype") for p in data["type-profiles"]} != scope:
            raise DomainError(
                "TYPE_COVERAGE_MISSING", "每个范围内类型都须有可用或明确缺口记录", 422
            )
        definitions = {
            p.property_id: p for p in map(PropertyDefinition.model_validate, data["definitions"])
        }
        profiles = {
            p.profile_id: p for p in map(OutputProfile.model_validate, data["output-profiles"])
        }
        if len(definitions) != len(data["definitions"]) or len(profiles) != len(
            data["output-profiles"]
        ):
            raise DomainError("DUPLICATE_DEFINITION", "性质或配置ID重复", 422)
        if len({p.quantity_key for p in definitions.values()}) != len(definitions):
            raise DomainError(
                "DUPLICATE_QUANTITY_IDENTITY", "同量科学身份不能重复发布为多个性质", 422
            )
        registry_objects = {}
        identity_keys = {
            "definitions": "property_id",
            "output-profiles": "profile_id",
            "families": "family_id",
            "subject-classes": "subject_class_id",
            "object-scales": "object_scale_id",
            "evidence": "evidence_id",
            "reviews": "review_id",
            "gaps": "gap_id",
            "conversion-policies": "policy_id",
        }
        for role, collection in data.items():
            if not isinstance(collection, list):
                continue
            for obj in collection:
                if not isinstance(obj, dict) or role in {"test-vectors", "type-profiles"}:
                    continue
                identity_key = identity_keys.get(role)
                identifier = obj.get(identity_key) if identity_key else None
                if identifier:
                    if identifier in registry_objects:
                        raise DomainError(
                            "DUPLICATE_REGISTRY_ID", "发布标识重复", 422, object_id=identifier
                        )
                    if obj.get("content_sha256") != content_hash(obj):
                        raise DomainError(
                            "REGISTRY_OBJECT_HASH", "发布对象哈希不匹配", 422, object_id=identifier
                        )
                    registry_objects[identifier] = obj
        composition = data["composition"]
        for rule in composition.get("rules", []):
            if rule["rule_id"] in registry_objects or rule.get("content_sha256") != content_hash(
                rule
            ):
                raise DomainError("RULE_HASH", "适用规则哈希或ID不合法", 422)
            registry_objects[rule["rule_id"]] = rule

        def walk(value):
            if isinstance(value, dict):
                if {"id", "version", "content_sha256"} <= value.keys():
                    target = registry_objects.get(value["id"])
                    if (
                        target is None
                        or target.get("content_sha256") != value["content_sha256"]
                        or target.get("version", target.get("definition_version"))
                        != value["version"]
                    ):
                        raise DomainError(
                            "DANGLING_REGISTRY_REF",
                            "发布引用缺失或版本不一致",
                            422,
                            object_id=value["id"],
                        )
                for key, child in value.items():
                    if key not in {"source_artifacts", "artifact_ref", "reviewed_ref"}:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        # review targets are checked separately; excluding them breaks intentional review-hash cycles.
        for role in (
            "definitions",
            "output-profiles",
            "families",
            "subject-classes",
            "object-scales",
            "composition",
        ):
            walk(data[role])
        reviews = {r["review_id"]: r for r in data["reviews"]}
        for obj in registry_objects.values():
            if "review_ref" not in obj:
                continue
            review = reviews.get(obj["review_ref"]["id"])
            reviewed_payload_hash = digest(
                {k: v for k, v in obj.items() if k not in {"content_sha256", "review_ref"}}
            )
            if (
                not review
                or review.get("decision") != "approved"
                or review.get("reviewed_payload_sha256") != reviewed_payload_hash
                or not review.get("checks")
            ):
                raise DomainError("INVALID_REVIEW", "审查回执未批准当前内容", 422)
        # The object still hashes its review_ref. The review signs the semantic
        # payload excluding that back-reference, so neither hash is self-referential.
        compiled = compile_rules(composition.get("rules", []), composition.get("exclusions", []))
        if data["compiled-support"].get("content_sha256") != compiled["content_sha256"]:
            raise DomainError("COMPILER_DIVERGENCE", "编译支持集与消费者重算不一致", 422)
        families = {f["family_id"]: f for f in data["families"]}
        for definition in definitions.values():
            family = families.get(definition.family_id)
            if not family or definition.property_id not in family.get("member_property_ids", []):
                raise DomainError("FAMILY_MAPPING", "性质缺少一致的检索族映射", 422)
        vectors = data["test-vectors"]
        if not vectors:
            raise DomainError("MISSING_TEST_VECTORS", "发布缺少消费者测试向量", 422)
        result = {
            "manifest": manifest,
            "data": data,
            "definitions": definitions,
            "profiles": profiles,
            "compiled": compiled,
            "objects": registry_objects,
        }
        for vector in vectors:
            support = self.support(result, vector["otypes"], vector["subject_class_id"])
            if [b["property_id"] for b in support["bindings"]] != vector["expected_property_ids"]:
                raise DomainError(
                    "REGISTRY_VECTOR_FAILED", "发布测试向量不匹配", 422, vector=vector.get("id")
                )
        return result

    def _validate_consumer(self, directory, manifest):
        from .consumer import consume_candidate

        if content_hash(manifest) != manifest.get("content_sha256"):
            raise DomainError("MANIFEST_HASH", "消费配置清单哈希不匹配", 422)
        cached = self._consumer_cache.get(str(directory))
        if cached and cached[0] == manifest:
            unchanged = all(path.stat().st_size == size and path.stat().st_mtime_ns == modified
                            for path, size, modified in cached[2])
            if unchanged:
                return cached[1]
        if (directory / "runtime-inputs.json.xz").is_file():
            from .distribution import load_verified_distribution
            result, files = load_verified_distribution(directory, manifest)
            self._consumer_cache[str(directory)] = (manifest, result, [
                (path, path.stat().st_size, path.stat().st_mtime_ns) for path in files])
            return result
        source = directory / "origin"
        result = consume_candidate(source, directory / "accepted-science-config.json",
            manifest_sha256=manifest["source_manifest_sha256"], config_sha256=manifest["science_config_sha256"],
            consumer_protocol=manifest.get('support_policy'),
            amendment=loads(self._file(directory, 'consumer-amendment.json').read_bytes()) if manifest.get('amendment_sha256') else None)
        if result["manifest"] != manifest:
            raise DomainError("CONSUMER_CONFIGURATION_CHANGED", "消费配置无法由原始审定资料重现", 422)
        from .candidate import local_file
        from .consumer import source_files
        files = [self._file(directory, "manifest.json"), self._file(directory, "accepted-science-config.json"),
                 *[local_file(source, name) for name in source_files(source, result["candidate"])]]
        if manifest.get('amendment_sha256'):
            files.append(self._file(directory, 'consumer-amendment.json'))
        self._consumer_cache[str(directory)] = (manifest, result, [(p, p.stat().st_size, p.stat().st_mtime_ns) for p in files])
        return result

    def import_candidate(self, package: Path, science_config: Path, *, manifest_sha256: str, config_sha256: str, amendment=None, activate=True):
        """Install a separate consumer configuration; never rewrite Dot flags."""
        from .candidate import local_file
        from .consumer import consume_candidate, source_files

        verified = consume_candidate(package.resolve(), science_config.resolve(),
            manifest_sha256=manifest_sha256, config_sha256=config_sha256, amendment=amendment)
        manifest = verified["manifest"]
        release_id = manifest["release_id"]
        destination = self.root / "releases" / release_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.repository.read() as conn:
            prior = conn.execute("SELECT * FROM registry_releases WHERE release_id=?", (release_id,)).fetchone()
            if prior:
                if prior["content_sha256"] != manifest["content_sha256"]:
                    raise DomainError("IMMUTABLE_RELEASE", "消费配置不能覆盖已有版本", 409)
                self.validate(destination)
                return {"release_id": release_id, "content_sha256": manifest["content_sha256"], "already_imported": True}
        temporary = destination.parent / (".import-" + new_id())
        temporary.mkdir()
        # Windows long paths are an IO detail, not a change to package names.
        def target_path(relative):
            target = (temporary / relative).resolve()
            if not target.is_relative_to(temporary.resolve()):
                raise DomainError("INVALID_RELEASE_PATH", "消费配置写入路径越界", 422)
            if os.name == "nt" and len(str(target)) >= 240:
                target = Path("\\\\?\\" + str(target))
            return target
        try:
            for name in source_files(package, verified["candidate"]):
                target = target_path("origin/" + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(local_file(package, name).read_bytes())
            (temporary / "accepted-science-config.json").write_bytes(science_config.read_bytes())
            if amendment is not None:
                (temporary / 'consumer-amendment.json').write_bytes(canonical(amendment))
            (temporary / "manifest.json").write_bytes(canonical(manifest))
            self.validate(temporary)
            with self.repository.transaction() as conn:
                if destination.exists():
                    raise DomainError("IMMUTABLE_RELEASE", "消费配置目录已存在", 409)
                os.replace(temporary, destination)
                conn.execute("INSERT INTO registry_releases VALUES(?,?,?,?,?,?)",
                    (release_id, manifest["content_sha256"], str(destination), "property", 0, utcnow()))
                if activate:
                    conn.execute("INSERT INTO settings VALUES('active_registry',?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=revision+1",
                        (canonical({"release_id": release_id, "content_sha256": manifest["content_sha256"]}),))
        finally:
            if temporary.exists() and temporary.resolve().parent == destination.parent.resolve() and temporary.name.startswith(".import-"):
                shutil.rmtree(temporary)
            self._consumer_cache.pop(str(temporary.resolve()), None)
        return {"release_id": release_id, "content_sha256": manifest["content_sha256"], "source_candidate_unchanged": True,
                'activated':activate}

    def import_release(self, directory: Path) -> dict:
        verified = self.validate(directory)
        manifest = verified["manifest"]
        release_id = manifest["release_id"]
        if (
            Path(release_id).name != release_id
            or any(c in release_id for c in ":\\/")
            or release_id in {".", ".."}
        ):
            raise DomainError("INVALID_RELEASE_ID", "发布ID不能用作目录名", 422)
        destination = self.root / "releases" / release_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.repository.read() as conn:
            old = conn.execute(
                "SELECT * FROM registry_releases WHERE release_id=?", (release_id,)
            ).fetchone()
            if old:
                if old["content_sha256"] != manifest["content_sha256"]:
                    raise DomainError("IMMUTABLE_RELEASE", "不能覆盖已有发布版本")
                return {
                    "release_id": release_id,
                    "content_sha256": old["content_sha256"],
                    "already_imported": True,
                }
        temporary = destination.parent / (".import-" + new_id())
        try:
            temporary.mkdir()
            for name in ["manifest.json", *[e["path"] for e in manifest["content_files"]]]:
                source = self._file(directory.resolve(), name)
                target = (temporary / name).resolve()
                if not target.is_relative_to(temporary.resolve()):
                    raise DomainError("INVALID_RELEASE_PATH", "发布路径超出暂存目录", 422)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(source.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
            self.validate(temporary)
            with self.repository.transaction() as conn:
                if destination.exists():
                    self.validate(destination)
                else:
                    os.replace(temporary, destination)
                conn.execute(
                    "INSERT INTO registry_releases VALUES(?,?,?,?,?,?)",
                    (
                        release_id,
                        manifest["content_sha256"],
                        str(destination),
                        "property",
                        int(manifest.get("synthetic", False)),
                        utcnow(),
                    ),
                )
                conn.execute(
                    "INSERT INTO settings VALUES('active_registry',?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=revision+1",
                    (
                        canonical(
                            {"release_id": release_id, "content_sha256": manifest["content_sha256"]}
                        ),
                    ),
                )
        finally:
            if temporary.exists():
                # Only the verified, private import staging directory is removed.
                shutil.rmtree(temporary)
        return {
            "release_id": release_id,
            "content_sha256": manifest["content_sha256"],
            "synthetic": manifest.get("synthetic", False),
        }

    def load(self, release_id: str | None = None) -> dict:
        with self.repository.read() as conn:
            if release_id is None:
                active = conn.execute(
                    "SELECT payload FROM settings WHERE key='active_registry'"
                ).fetchone()
                if not active:
                    raise DomainError("REGISTRY_MISSING", "性质库尚未就绪，请先导入Dot正式发布包")
                release_id = loads(active[0])["release_id"]
            row = conn.execute(
                "SELECT * FROM registry_releases WHERE release_id=? AND kind='property'",
                (release_id,),
            ).fetchone()
            if not row:
                raise DomainError("REGISTRY_MISSING", "指定性质库版本不可用")
            path = Path(row["path"])
        verified = self.validate(path)
        if verified["manifest"]["content_sha256"] != row["content_sha256"]:
            raise DomainError("CORRUPT_RELEASE", "已导入的发布发生变化")
        return verified

    def check_eligibility(self, conn, release_id: str, dependency_refs: list[dict]) -> dict:
        ids = {r["id"] for r in dependency_refs}
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM revocations WHERE release_id=? ORDER BY revision", (release_id,)
            )
        ]
        impacts = [r for r in rows if r["dependency_id"] is None or r["dependency_id"] in ids]
        return {
            "state": "blocked" if impacts else "eligible",
            "eligibility_revision": max((r["revision"] for r in rows), default=0),
            "impacts": [{k: v for k, v in row.items() if k != "evidence"} for row in impacts],
        }

    @staticmethod
    def support(release: dict, otypes: list[str], subject_class_id: str) -> dict:
        if release["manifest"].get("schema_version") == "registry-candidate-consumer/1":
            from .consumer import consumer_support
            return consumer_support(release, otypes, subject_class_id)
        compiled = release["compiled"]
        types = set(otypes)
        if any(matches(c, types, subject_class_id) for c in compiled["exclusions"]):
            return {"bindings": [], "gaps": [{"reason": "excluded_composition"}]}
        selected, display_orders = {}, {}

        def dependency_closure(roots):
            found = {}

            def visit(value):
                if isinstance(value, list):
                    for item in value:
                        visit(item)
                elif isinstance(value, dict):
                    if {"id", "version", "content_sha256"} <= value.keys():
                        reference = {key: value[key] for key in ("id", "version", "content_sha256")}
                        key = digest(reference)
                        if key not in found:
                            found[key] = reference
                            visit(release["objects"][reference["id"]])
                    else:
                        for item in value.values():
                            visit(item)

            visit(roots)
            return sorted(
                found.values(), key=lambda ref: (ref["id"], ref["version"], ref["content_sha256"])
            )

        def object_reference(identifier):
            obj = release["objects"][identifier]
            return {
                "id": identifier,
                "version": obj.get("version", obj.get("definition_version")),
                "content_sha256": obj["content_sha256"],
            }

        for rule in compiled["rules"]:
            if not matches(rule["condition"], types, subject_class_id):
                continue
            definition = release["definitions"][rule["definition_ref"]["id"]]
            profile = release["profiles"][rule["profile_ref"]["id"]]
            if definition.subject_class_id != subject_class_id:
                raise DomainError("SUBJECT_CONFLICT", "适用规则与性质主体不一致")
            rule_ref = {
                "id": rule["rule_id"],
                "version": rule["version"],
                "content_sha256": rule["content_sha256"],
            }
            pid = definition.property_id
            display_orders[pid] = min(
                display_orders.get(pid, rule.get("display_order", 0)), rule.get("display_order", 0)
            )
            if pid in selected:
                if selected[pid]["output_profile"] != profile.model_dump():
                    raise DomainError("UNRESOLVED_COMPOSITION", "运行支持集出现多个输出配置")
                selected[pid]["rule_refs"].append(rule_ref)
                selected[pid]["dependency_refs"].append(rule_ref)
            else:
                deps = [
                    rule["definition_ref"],
                    rule["profile_ref"],
                    rule_ref,
                    object_reference(definition.family_id),
                    object_reference(definition.subject_class_id),
                    object_reference(profile.object_scale_id),
                ]
                selected[pid] = PropertyBinding(
                    property_id=pid,
                    definition=definition,
                    output_profile=profile,
                    dependency_refs=deps,
                    rule_refs=[rule_ref],
                ).model_dump(mode="json")
        for binding in selected.values():
            binding["dependency_refs"] = dependency_closure(binding["dependency_refs"])
        bindings = sorted(
            selected.values(), key=lambda b: (display_orders[b["property_id"]], b["property_id"])
        )
        semantic = {
            "otypes": sorted(types),
            "subject_class_id": subject_class_id,
            "bindings": bindings,
        }
        return {**semantic, "support_hash": digest(semantic), "gaps": []}
