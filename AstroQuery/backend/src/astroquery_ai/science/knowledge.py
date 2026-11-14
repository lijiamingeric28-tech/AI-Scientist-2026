"""Reviewed theory consumers. This module never constructs scientific content."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from copy import deepcopy
from pathlib import Path

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, new_id, utcnow
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import Ref


def entry_hash(entry):
    return digest(
        {
            key: value
            for key, value in entry.items()
            if key not in {"content_hash", "content_sha256"}
        }
    )


class KnowledgeService:
    @staticmethod
    def inspect_author_package(directory,inventory,**kwargs):
        from .author_knowledge import inspect_author_package
        return inspect_author_package(directory,inventory,**kwargs)

    def __init__(self, root: Path, repository, registry):
        self.root, self.repository, self.registry = root.resolve(), repository, registry
        self._validation_lock = threading.RLock()
        self._validated_author = {}

    def validate(self, directory: Path):
        try:
            with self._validation_lock:
                directory = directory.resolve()
                if not (directory/'manifest.json').is_file():
                    return self._validate(directory)
                manifest = loads((directory/'manifest.json').read_bytes())
                if manifest.get('schema_version') != 'insight-knowledge/3':
                    return self._validate(directory)
                paths = [(directory/item['path']).resolve() for item in manifest['content_files']]
                if any(not p.is_relative_to(directory) or not p.is_file() for p in paths):
                    return self._validate(directory)
                signature = (digest(manifest), bool(getattr(self.registry,'allow_synthetic',False)), tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths))
                cached = self._validated_author.get(str(directory))
                if cached and cached[0] == signature:
                    registry = self.registry.load(manifest['registry_release_ref']['id'])
                    if registry['manifest']['content_sha256'] != manifest['registry_release_ref']['content_sha256']:
                        raise DomainError('KB_REGISTRY_BINDING','知识库绑定的性质库内容不一致',422)
                    return deepcopy(cached[1])
                result = self._validate(directory)
                if len(self._validated_author) >= 4:
                    self._validated_author.pop(next(iter(self._validated_author)))
                self._validated_author[str(directory)] = (signature,deepcopy(result))
                return result
        except DomainError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise DomainError("KB_RELEASE_SCHEMA", "知识库结构、字段或文件不可核验", 422) from exc

    def _validate(self, directory: Path):
        directory = directory.resolve()
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise DomainError("KB_MISSING_MANIFEST", "知识库缺少发布清单", 422)
        manifest = loads(manifest_path.read_bytes())
        if manifest.get('schema_version') == 'insight-knowledge-workspace/1':
            from astroquery_ai.registry.workspace_release import load_workspace_knowledge
            return load_workspace_knowledge(self, directory, manifest)
        if (
            manifest.get("schema_version") not in {"insight-knowledge/1", "insight-knowledge/2", "insight-knowledge/3"}
            or manifest.get("status") != "ready_to_import"
        ):
            raise DomainError("KB_RELEASE_SCHEMA", "知识库不是可导入的当前协议发布", 422)
        if manifest.get("content_sha256") != content_hash(manifest):
            raise DomainError("KB_MANIFEST_HASH", "知识库清单校验失败", 422)
        if manifest.get("synthetic") and not self.registry.allow_synthetic:
            raise DomainError("SYNTHETIC_KB", "合成知识库不能用于正式运行", 422)
        registry_ref = manifest.get("registry_release_ref")
        if not isinstance(registry_ref, dict):
            raise DomainError("KB_REGISTRY_BINDING", "知识库必须绑定真实性质库版本", 422)
        Ref.model_validate(registry_ref)
        if registry_ref["version"] != 1:
            raise DomainError("KB_REGISTRY_BINDING", "发布引用版本不受当前不可变发布协议支持", 422)
        registry = self.registry.load(registry_ref["id"])
        if registry["manifest"]["content_sha256"] != registry_ref["content_sha256"]:
            raise DomainError("KB_REGISTRY_BINDING", "知识库绑定的性质库内容不一致", 422)
        if manifest['schema_version']=='insight-knowledge/3':
            from .author_release import validate_release
            return validate_release(directory,manifest,registry)
        data = {}
        for item in manifest.get("content_files", []):
            path = (directory / item["path"]).resolve()
            if (
                not path.is_relative_to(directory)
                or not path.is_file()
                or path == manifest_path
                or item["role"] in data
            ):
                raise DomainError("KB_CONTENT_PATH", "知识库文件缺失、重复或路径非法", 422)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise DomainError("KB_CONTENT_HASH", "知识库文件校验失败", 422)
            data[item["role"]] = loads(raw)
        required = {"entries", "sources", "bindings", "index", "coverage", "reviews"}
        if required - data.keys():
            raise DomainError("KB_FILES_MISSING", "知识库缺少强制文件角色", 422)
        content = None
        if manifest['schema_version'] == 'insight-knowledge/2':
            from .bound_knowledge import bound_content
            content = bound_content(directory, manifest, data)
        for key in {"entries", "sources", "bindings", "reviews"}:
            if not isinstance(data[key], list):
                raise DomainError("KB_COLLECTION_SCHEMA", "知识库对象集合必须为数组", 422)
        entries = {e["entry_id"]: e for e in data["entries"]}
        sources = {s["source_id"]: s for s in data["sources"]}
        reviews = {r["review_id"]: r for r in data["reviews"]}
        if (
            len(entries) != len(data["entries"])
            or len(sources) != len(data["sources"])
            or len(reviews) != len(data["reviews"])
        ):
            raise DomainError("KB_DUPLICATE_ID", "知识库标识重复", 422)
        evidence_items = [e for source in sources.values() for e in source["evidence"]]
        evidence = {e["evidence_id"]: e for e in evidence_items}
        if len(evidence) != len(evidence_items):
            raise DomainError("KB_DUPLICATE_ID", "知识证据标识重复", 422)

        def review_for(obj):
            reference = obj["review_ref"]
            review = reviews.get(reference["id"])
            semantic_hash = digest(
                {
                    k: v
                    for k, v in obj.items()
                    if k not in {"content_hash", "content_sha256", "review_ref"}
                }
            )
            if (
                not review
                or review.get("decision") != "approved"
                or review.get("unresolved")
                or review.get("reviewed_payload_sha256") != semantic_hash
            ):
                raise DomainError("KB_REVIEW_STALE", "知识条目或绑定未经当前内容审核", 422)
            if (
                reference["version"] != review["review_version"]
                or reference["content_sha256"] != content_hash(review)
                or review.get("content_sha256") != content_hash(review)
            ):
                raise DomainError("KB_REVIEW_REFERENCE", "知识审核版本或哈希不一致", 422)
            return review

        for source in sources.values():
            if not source.get("identity") or not source.get("qualification"):
                raise DomainError("KB_SOURCE_IDENTITY", "理论来源缺少身份或资格记录", 422)
            for piece in source["evidence"]:
                if (
                    not piece.get("locator")
                    or not piece.get("excerpt")
                    or piece.get("excerpt_hash")
                    != hashlib.sha256(piece["excerpt"].encode()).hexdigest()
                ):
                    raise DomainError("KB_SOURCE_EVIDENCE", "理论证据缺少定位、原文或一致哈希", 422)
        for entry in entries.values():
            # The original content loader checks every claim, evidence and author
            # review against its own immutable hash. Only bindings are newly
            # reviewed; an author_checked review is never renamed approved.
            if content is not None:
                continue
            if entry.get("schema_version") != "InsightKnowledgeEntry/1" or entry.get(
                "content_hash"
            ) != entry_hash(entry):
                raise DomainError("KB_ENTRY_HASH", "知识条目协议或内容哈希错误", 422)
            if entry.get("kind") not in {
                "concept",
                "measurement_method",
                "physical_law",
                "empirical_relation",
                "reference_range",
                "usage_limitation",
            }:
                raise DomainError("KB_ENTRY_KIND", "未知知识条目类别", 422)
            if not entry.get("claims") or not entry.get("subject_scope"):
                raise DomainError("KB_CLAIMS_MISSING", "知识条目缺少声明或主体范围", 422)
            review_for(entry)
            if len({claim["claim_id"] for claim in entry["claims"]}) != len(entry["claims"]):
                raise DomainError("KB_DUPLICATE_ID", "条目内声明标识重复", 422)
            for claim in entry["claims"]:
                if not claim.get("statement_zh") or not claim.get("evidence_refs"):
                    raise DomainError("KB_CLAIM_EVIDENCE", "理论声明缺少内容或证据", 422)
                if any(ref["id"] not in evidence for ref in claim["evidence_refs"]):
                    raise DomainError("KB_DANGLING_EVIDENCE", "理论声明引用不可解析", 422)
                for reference in claim["evidence_refs"]:
                    piece = evidence[reference["id"]]
                    if (
                        reference["content_sha256"] != content_hash(piece)
                        or reference["version"] != piece["revision"]
                        or claim["claim_id"] not in piece["supports_claim_ids"]
                    ):
                        raise DomainError(
                            "KB_EVIDENCE_REFERENCE", "声明引用的证据版本、内容或支持关系不一致", 422
                        )
        if len({b['binding_id'] for b in data['bindings']}) != len(data['bindings']):
            raise DomainError('KB_DUPLICATE_ID', '理论绑定标识重复', 422)
        for binding in data["bindings"]:
            review_for(binding)
            if not binding['property_bindings'] or not binding['subject_class_ids'] or not binding['object_scale']:
                raise DomainError('KB_DEFINITION_BINDING', '理论绑定缺少具体性质、主体或尺度', 422)
            if binding["registry_release_ref"] != registry_ref:
                raise DomainError("KB_REGISTRY_BINDING", "知识绑定使用了另一性质库版本", 422)
            entry = entries.get(binding["entry_ref"]["id"])
            if (
                not entry
                or binding["entry_ref"]["content_sha256"] != entry["content_hash"]
                or binding["entry_ref"]["version"] != entry["revision"]
            ):
                raise DomainError("KB_ENTRY_BINDING", "知识绑定指向不存在或过期条目", 422)
            if content is not None and (not binding['otype_scope']
                    or not set(binding['otype_scope']) <= set(entry['otype_scope'])):
                raise DomainError('KB_SUBJECT_BINDING', '正式绑定不能扩大原内容的类型范围', 422)
            for prop in binding["property_bindings"]:
                from astroquery_ai.registry.projection import definition_view,output_profile_view
                from astroquery_ai.registry.amendments import reference_key
                actual=definition_view(registry,prop['property_id'],prop['definition_version'],prop['definition_hash'])
                if (
                    not actual
                    or actual.definition_version != prop["definition_version"]
                    or actual.content_sha256 != prop["definition_hash"]
                ):
                    raise DomainError("KB_DEFINITION_BINDING", "知识绑定使用了不同科学定义", 422)
                output_ref = prop.get("output_profile_ref")
                if output_ref:
                    profile=output_profile_view(registry,output_ref)
                    if (not profile or profile.property_id != prop["property_id"] or profile.version != output_ref["version"]
                            or profile.content_sha256 != output_ref["content_sha256"]):
                        raise DomainError("KB_OUTPUT_BINDING", "知识绑定使用了不同输出表示", 422)
                source_ref = prop.get("source_definition_ref")
                exact_source=registry.get('source_definition_refs',{}).get(reference_key({
                    'id':prop['property_id'],'version':prop['definition_version'],'content_sha256':prop['definition_hash']}))
                exact_sources=exact_source if isinstance(exact_source,list) else ([exact_source] if exact_source else [])
                legacy_source=registry.get('science',{}).get('records',{}).get(prop['property_id'],{}).get('definition_ref')
                if legacy_source:exact_sources.append(legacy_source)
                if source_ref and source_ref not in exact_sources:
                    raise DomainError("KB_SOURCE_DEFINITION", "知识绑定未对应准确原始科学定义", 422)
            approved_claims = {c["claim_id"] for c in entry["claims"]}
            if not binding["claim_ids"] or set(binding["claim_ids"]) - approved_claims:
                raise DomainError("KB_CLAIM_BINDING", "知识绑定声明集合无效", 422)
            mappings = binding.get("content_condition_bindings")
            if mappings is not None:
                condition_ids = {c["condition_id"] for c in entry.get("conditions", [])}
                if (not isinstance(mappings, list) or len(mappings) != len(condition_ids)
                        or {m.get("condition_id") for m in mappings} != condition_ids):
                    raise DomainError("KB_CONDITION_BINDING", "正式条件映射必须逐项对应原知识条件", 422)
                allowed = {"frozen_subject", "frozen_definition", "reported_context", "conditional_background"}
                known_keys = set()
                for prop in binding["property_bindings"]:
                    actual=definition_view(registry,prop['property_id'],prop['definition_version'],prop['definition_hash'])
                    known_keys.update(c.key for c in actual.measurement_conditions_schema)
                    from astroquery_ai.registry.science_conditions import scoped_conditions
                    for choice in scoped_conditions(registry.get('science',{}),prop['property_id'],binding['otype_scope']):
                        if not prop.get('source_definition_ref') or choice['record']['definition_ref']==prop['source_definition_ref']:
                            known_keys.update(c['key'] for c in choice['record'].get('context_contracts',[]))
                for mapping in mappings:
                    if mapping.get("mode") not in allowed or not mapping.get("explanation"):
                        raise DomainError("KB_CONDITION_BINDING", "知识条件映射缺少明确方式或解释", 422)
                    if mapping["mode"] == "reported_context" and mapping.get("key") not in known_keys:
                        raise DomainError("KB_CONDITION_BINDING", "知识条件不能使用未审上下文字段", 422)
        return {"manifest": manifest, "data": data, "entries": entries, "sources": sources, 'content': content}

    def import_release(self, directory: Path, *, activate=True):
        release = self.validate(directory)
        manifest, release_id = release["manifest"], release["manifest"]["release_id"]
        if (
            Path(release_id).name != release_id
            or any(c in release_id for c in ":\\/")
            or release_id in {".", ".."}
        ):
            raise DomainError("KB_RELEASE_ID", "知识发布ID不可作为目录名", 422)
        destination = self.root / "releases" / release_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / (".import-" + new_id())
        with self.repository.read() as conn:
            old = conn.execute(
                "SELECT * FROM registry_releases WHERE release_id=?", (release_id,)
            ).fetchone()
        if old:
            if old["content_sha256"] != manifest["content_sha256"] or old["kind"] != "knowledge":
                raise DomainError("KB_IMMUTABLE_RELEASE", "不可覆盖已有发布身份")
            return {"release_id": release_id, "already_imported": True}
        try:
            temporary.mkdir()
            for name in ["manifest.json", *[item["path"] for item in manifest["content_files"]]]:
                source, target = (directory / name).resolve(), (temporary / name).resolve()
                if not target.is_relative_to(temporary.resolve()) or not source.is_relative_to(
                    directory.resolve()
                ):
                    raise DomainError("KB_CONTENT_PATH", "知识发布路径越界", 422)
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
                        "knowledge",
                        int(manifest.get("synthetic", False)),
                        utcnow(),
                    ),
                )
                if activate:
                    conn.execute(
                        "INSERT INTO settings VALUES('active_knowledge',?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=revision+1",
                        (canonical({"id": release_id, "content_sha256": manifest["content_sha256"]}),),
                    )
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return {"release_id": release_id, "content_sha256": manifest["content_sha256"], 'activated':activate}

    def load(self, reference=None):
        with self.repository.read() as conn:
            if reference is None:
                active = conn.execute(
                    "SELECT payload FROM settings WHERE key='active_knowledge'"
                ).fetchone()
                if not active:
                    raise DomainError("KB_UNAVAILABLE", "缺少已核对理论依据")
                reference = loads(active[0])
            release = conn.execute(
                "SELECT * FROM registry_releases WHERE release_id=? AND kind='knowledge'",
                (reference["id"],),
            ).fetchone()
            if conn.execute(
                "SELECT 1 FROM revocations WHERE release_id=? LIMIT 1", (reference["id"],)
            ).fetchone():
                raise DomainError("KB_REVOKED", "已绑定知识版本存在撤回记录")
            if release:
                manifest = loads((Path(release["path"]) / "manifest.json").read_bytes())
                if conn.execute(
                    "SELECT 1 FROM revocations WHERE release_id=? LIMIT 1",
                    (manifest["registry_release_ref"]["id"],),
                ).fetchone():
                    raise DomainError("KB_REGISTRY_REVOKED", "知识所依赖性质版本存在撤回记录")
        if not release:
            raise DomainError("KB_UNAVAILABLE", "已登记知识库发布不可用")
        result = self.validate(Path(release["path"]))
        if result["manifest"]["content_sha256"] != reference["content_sha256"]:
            raise DomainError("KB_UNAVAILABLE", "知识库内容已变化")
        return result

    def select(self, release, query, contexts):
        selected = {b["property_id"]: b for b in query["properties"]}
        assertions = query["target"]["classification_assertions"]
        types = {a["canonical_otype"] for a in assertions if a.get("state") == "current_verified"}
        types.add(query["target"]["primary_otype"])
        choices = []
        for binding in release["data"]["bindings"]:
            if binding["registry_release_ref"] != query["registry_release"]:
                continue
            props = binding["property_bindings"]
            if not props or any(p["property_id"] not in selected for p in props):
                continue
            if any(
                selected[p["property_id"]]["definition"]["content_sha256"] != p["definition_hash"]
                for p in props
            ):
                continue
            if any(p.get("output_profile_ref") and p["output_profile_ref"] != {
                    "id": selected[p["property_id"]]["output_profile"]["profile_id"],
                    "version": selected[p["property_id"]]["output_profile"]["version"],
                    "content_sha256": selected[p["property_id"]]["output_profile"]["content_sha256"]} for p in props):
                continue
            if not types.intersection(binding["otype_scope"]):
                continue
            if any(
                selected[p["property_id"]]["definition"]["subject_class_id"]
                not in binding["subject_class_ids"]
                for p in props
            ):
                continue
            if any(
                selected[p["property_id"]]["output_profile"]["object_scale_id"]
                != binding["object_scale"]
                for p in props
            ):
                continue
            entry = release["entries"][binding["entry_ref"]["id"]]
            requirements = binding["required_conditions"]
            # Conditions bind to each specific measurement; source-level unknowns
            # never count as target conditions. Preserve unknown background only.
            condition_states = []
            author_conditions=binding.get('author_subject_conditions') or {}
            if author_conditions:
                # Preserve author-supplied boundary prose as conditional unless
                # it has an explicit executable mapping. It is not a new fact.
                condition_states.append('unknown')
            # Unmapped prose conditions remain unknown. Matching a broad type
            # never silently establishes frequency, epoch, method or scope.
            relevant_contexts = [
                context
                for context in contexts
                if context["snapshot_binding"].get("property", {}).get("id")
                in {p["property_id"] for p in props}
            ]
            content_conditions = []
            if entry.get('schema_version') == 'insight-content-entry/1':
                mappings = binding.get("content_condition_bindings")
                if mappings is None:
                    if entry.get('conditions') or entry.get('conditions_zh'):
                        condition_states.append('unknown')
                else:
                    for mapping in mappings:
                        mode = mapping["mode"]
                        state = "unknown"
                        if mode in {"frozen_subject", "frozen_definition"}:
                            # Exact type/subject/scale and definition checks above
                            # establish only the explicitly reviewed mapping.
                            state = "met"
                        elif mode == "reported_context":
                            values = [next((c for c in context["conditions"] if c["key"] == mapping["key"]), None)
                                      for context in relevant_contexts]
                            if values and all(v is not None and v["state"] == "known" for v in values):
                                state = "met" if "equals" not in mapping or all(v["value"] == mapping["equals"] for v in values) else "not_met"
                        content_conditions.append({"condition_id": mapping["condition_id"], "state": state,
                                                   "explanation": mapping["explanation"]})
                        condition_states.append(state)
            for requirement in requirements:
                key, expected = requirement["key"], requirement["equals"]
                values = [
                    next(
                        (c for c in context["conditions"] if c["key"] == key),
                        {"state": "not_checked", "value": None},
                    )
                    for context in relevant_contexts
                ]
                condition_states.append(
                    "unknown"
                    if not values or any(c["state"] != "known" for c in values)
                    else "met"
                    if all(c["value"] == expected for c in values)
                    else "not_met"
                )
            for exclusion in binding["excluded_conditions"]:
                values = [
                    next(
                        (c for c in context["conditions"] if c["key"] == exclusion["key"]),
                        {"state": "not_checked", "value": None},
                    )
                    for context in relevant_contexts
                ]
                if any(c["state"] == "known" and c["value"] == exclusion["equals"] for c in values):
                    condition_states.append("not_met")
                elif not values or any(c["state"] != "known" for c in values):
                    condition_states.append("unknown")
            if "not_met" in condition_states:
                continue
            scope = (
                "conditional_background"
                if "unknown" in condition_states
                else "applicable_background"
            )
            for claim in entry["claims"]:
                if claim["claim_id"] in binding["claim_ids"]:
                    claim = dict(claim)
                    basis = claim.get('authoring_basis', 'source_verified')
                    claim['authoring_basis'] = basis
                    claim['basis_label'] = '作者知识整理' if basis == 'author_knowledge' else '来源已核查'
                    claim['evidence_refs'] = [ref if isinstance(ref, dict) else {
                        'id': ref, 'version': 1, 'content_sha256': content_hash(next(
                            piece for source in release['sources'].values() for piece in source['evidence']
                            if piece['evidence_id'] == ref))} for ref in claim['evidence_refs']]
                    choices.append(
                        {
                            "entry_ref": binding["entry_ref"],
                            "claim": claim,
                            "scope": scope,
                            "conditions": requirements,
                            "property_ids": [p["property_id"] for p in props],
                            "kind": entry["kind"],
                            "limitations": entry.get('caveats', [entry['limitations_zh']] if 'limitations_zh' in entry else []),
                            "title_zh": entry.get("title_zh", entry.get('title')),
                            'conditions_zh': entry.get('conditions_zh'),
                            'content_conditions': entry.get('conditions', []),
                            'content_condition_evaluation': content_conditions,
                            **({'binding_conditions':author_conditions} if author_conditions else {}),
                            'uncertainty_notes': entry.get('uncertainty_notes'),
                            'formula': entry.get('formula') if binding.get('include_formula', True) else None,
                            'author_review': next((r for r in (release.get('content') or {}).get('files', {}).get('content/reviews.json', [])
                                                   if r['review_id'] == entry.get('review_id')), None),
                            "sources": [
                                {**{key: value for key, value in source.items() if key != "evidence"},
                                 "evidence": [piece for piece in source["evidence"]
                                              if piece["evidence_id"] in {ref["id"] for ref in claim["evidence_refs"]}]}
                                for source in release["sources"].values()
                                if any(piece["evidence_id"] in {ref["id"] for ref in claim["evidence_refs"]}
                                       for piece in source["evidence"])
                            ],
                        }
                    )
        unique = {}
        for choice in choices:
            key = digest({"entry": choice["entry_ref"], "claim": choice["claim"]["claim_id"], "scope": choice["scope"],
                          "conditions": choice["conditions"], "content_condition_evaluation": choice["content_condition_evaluation"],
                          'binding_conditions':choice.get('binding_conditions',{})})
            if key in unique:
                unique[key]["property_ids"] = sorted(set(unique[key]["property_ids"]) | set(choice["property_ids"]))
            else:
                unique[key] = choice
        return list(unique.values())
