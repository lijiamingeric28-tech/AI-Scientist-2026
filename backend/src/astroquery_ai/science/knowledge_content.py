"""Read genuine theory content separately from formally bound runtime knowledge."""

from __future__ import annotations

import hashlib
from pathlib import Path

from astroquery_ai.registry.candidate import local_file
from astroquery_ai.runtime.codec import digest, loads
from astroquery_ai.runtime.errors import DomainError


def payload_hash(value):
    return digest({key: item for key, item in value.items() if key != "content_hash"})


class KnowledgeContent:
    def load(self, root: Path):
        try:
            return self._load(root)
        except DomainError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise DomainError(
                "KNOWLEDGE_CONTENT_SCHEMA", "理论内容字段、文件或引用不可核验", 422
            ) from exc

    def _load(self, root):
        manifest = loads(local_file(root, "content-manifest.json").read_bytes())
        if (
            manifest.get("schema_version") != "insight-content/1"
            or manifest.get("status") != "content_ready_bindings_pending"
            or manifest.get("activation_allowed") is not False
        ):
            raise DomainError(
                "KNOWLEDGE_CONTENT_STATE", "理论内容不是已完成且待绑定的当前协议版本", 422
            )
        if manifest["content_hash"] != payload_hash(manifest):
            raise DomainError("KNOWLEDGE_CONTENT_HASH", "理论内容清单哈希不一致", 422)
        files = {}
        for relative, expected in manifest["files"].items():
            path = local_file(root, relative)
            if path.stat().st_size > 32 * 1024**2:
                raise DomainError("KNOWLEDGE_CONTENT_LIMIT", "单个理论内容文件过大", 422)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise DomainError(
                    "KNOWLEDGE_CONTENT_FILE_HASH",
                    "理论文件原字节哈希不一致",
                    422,
                    relative=relative,
                )
            files[relative] = loads(raw)
        entries = files["content/entries.json"]
        sources = files["content/sources.json"]
        reviews = {review["review_id"]: review for review in files["content/reviews.json"]}
        evidence = {}
        for source in sources:
            if source["availability"] != "opened_and_read" or not source["identity"][
                "url"
            ].startswith("https://"):
                raise DomainError("KNOWLEDGE_SOURCE_NOT_READ", "来源核查分支缺少已阅读身份", 422)
            for piece in source["evidence"]:
                if (
                    piece["evidence_id"] in evidence
                    or piece["excerpt_hash"]
                    != hashlib.sha256(piece["excerpt"].encode()).hexdigest()
                    or not piece["locator"]
                ):
                    raise DomainError(
                        "KNOWLEDGE_SOURCE_EVIDENCE", "核查证据重复或定位/哈希无效", 422
                    )
                evidence[piece["evidence_id"]] = {
                    "evidence": piece,
                    "source": {k: v for k, v in source.items() if k != "evidence"},
                }
        scope = {item["id"] for item in files["inputs/scope.json"]["types"]}
        ids, claims = set(), set()
        for entry in entries:
            if (
                entry["entry_id"] in ids
                or entry["content_hash"] != payload_hash(entry)
                or not set(entry["otype_scope"]) <= scope
            ):
                raise DomainError("KNOWLEDGE_ENTRY_HASH", "理论条目标识、范围或哈希不一致", 422)
            ids.add(entry["entry_id"])
            if (
                entry.get("usage") != "background_only"
                or entry.get("allows_new_measurement") is not False
                or entry.get("allows_quality_score") is not False
            ):
                raise DomainError(
                    "KNOWLEDGE_CONTENT_AUTHORITY", "理论内容不能获得测量/评分权限", 422
                )
            if entry.get("formula") and entry["formula"].get("execution") != "forbidden":
                raise DomainError("KNOWLEDGE_FORMULA_EXECUTION", "理论公式只能展示", 422)
            if any(
                not entry.get(key)
                for key in ("conditions_zh", "limitations_zh", "uncertainty_notes")
            ):
                raise DomainError(
                    "KNOWLEDGE_CONTEXT_MISSING", "理论适用条件或不确定度限制缺失", 422
                )
            review = reviews.get(entry["review_id"])
            if (
                not review
                or review["entry_ref"]["content_hash"] != entry["content_hash"]
                or review["decision"] != "author_checked"
                or review["independent_human_review"] is not False
            ):
                raise DomainError(
                    "KNOWLEDGE_AUTHOR_REVIEW", "作者复核引用不一致或冒充独立人工审核", 422
                )
            for claim in entry["claims"]:
                if claim["claim_id"] in claims:
                    raise DomainError("KNOWLEDGE_CLAIM_DUPLICATE", "声明标识重复", 422)
                claims.add(claim["claim_id"])
                basis = claim["authoring_basis"]
                if basis not in {"author_knowledge", "source_verified"}:
                    raise DomainError("KNOWLEDGE_AUTHORING_BASIS", "声明来源类型不受支持", 422)
                if basis == "source_verified" and not claim["evidence_refs"]:
                    raise DomainError(
                        "KNOWLEDGE_VERIFIED_WITHOUT_EVIDENCE", "来源已核查的声明必须有定位证据", 422
                    )
                for identifier in claim["evidence_refs"]:
                    if (
                        identifier not in evidence
                        or claim["claim_id"]
                        not in evidence[identifier]["evidence"]["supports_claim_ids"]
                    ):
                        raise DomainError(
                            "KNOWLEDGE_CLAIM_SUPPORT", "声明与证据支持关系不一致", 422
                        )
        binding = files["content/bindings.json"]
        if binding["registry_release_ref"] is not None or binding["bindings"]:
            raise DomainError("KNOWLEDGE_UNEXPECTED_BINDING", "内容包不能冒充正式运行绑定", 422)
        return {
            "manifest": manifest,
            "entries": entries,
            "sources": sources,
            "evidence": evidence,
            "types": sorted(scope),
            "files": files,
            "report": {
                "schema_version": "knowledge-content-consumer-inspection/1",
                "release_id": manifest["release_id"],
                "content_hash": manifest["content_hash"],
                "entries": len(entries),
                "types": len(scope),
                "claims": len(claims),
                "source_verified_claims": sum(
                    claim["authoring_basis"] == "source_verified"
                    for entry in entries
                    for claim in entry["claims"]
                ),
                "author_knowledge_claims": sum(
                    claim["authoring_basis"] == "author_knowledge"
                    for entry in entries
                    for claim in entry["claims"]
                ),
                "verified_files": len(files),
                "binding_status": "pending",
                "runtime_authorized": False,
            },
        }

    def preview(self, release, otype):
        if otype not in release["types"]:
            raise DomainError("KNOWLEDGE_OTYPE_OUTSIDE_SCOPE", "该类型不在内容快照范围内", 422)
        return {
            "schema_version": "knowledge-content-preview/1",
            "content_release_ref": {
                "id": release["manifest"]["release_id"],
                "content_hash": release["manifest"]["content_hash"],
            },
            "otype": otype,
            "available_types": release["types"],
            "status": "unbound_preview",
            "target_applicability": "not_established",
            "runtime_authorized": False,
            "entries": [
                {
                    **entry,
                    "claims": [
                        {
                            **claim,
                            "basis_label": "作者知识整理"
                            if claim["authoring_basis"] == "author_knowledge"
                            else "来源已核查",
                            "source_evidence": [
                                release["evidence"][identifier]
                                for identifier in claim["evidence_refs"]
                            ],
                        }
                        for claim in entry["claims"]
                    ],
                }
                for entry in release["entries"]
                if otype in entry["otype_scope"]
            ],
        }
