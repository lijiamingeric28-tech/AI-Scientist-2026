"""Consumer structure only: all claims explicitly synthetic, never science content."""

import asyncio
import hashlib

import pytest

from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.knowledge import entry_hash
from tests.rebuild.scenario import application, confirmed_case


def package(app, path, release_id="synthetic-kb"):
    registry = app.registry.load()
    registry_ref = {
        "id": registry["manifest"]["release_id"],
        "version": 1,
        "content_sha256": registry["manifest"]["content_sha256"],
    }
    definition = registry["data"]["definitions"][0]
    piece = {
        "evidence_id": "synthetic-kb-evidence",
        "revision": 1,
        "locator": "synthetic fixture line 1",
        "excerpt": "SYNTHETIC software test, not a scientific claim",
        "supports_claim_ids": ["synthetic-claim"],
        "limitations": ["software fixture only"],
    }
    piece["excerpt_hash"] = hashlib.sha256(piece["excerpt"].encode()).hexdigest()
    piece_ref = {"id": piece["evidence_id"], "version": 1, "content_sha256": content_hash(piece)}
    entry = {
        "schema_version": "InsightKnowledgeEntry/1",
        "entry_id": "synthetic-entry",
        "revision": 1,
        "kind": "concept",
        "title": "SYNTHETIC",
        "subject_scope": {"description": "synthetic whole object"},
        "claims": [
            {
                "claim_id": "synthetic-claim",
                "statement_zh": "这是软件测试夹具，不是科学声明。",
                "evidence_refs": [piece_ref],
            }
        ],
        "caveats": ["synthetic"],
    }
    reviews = []

    def reviewed(obj, identifier):
        review = {
            "review_id": "review-" + identifier,
            "review_version": 1,
            "decision": "approved",
            "reviewer_kind": "synthetic_fixture",
            "unresolved": [],
            "reviewed_payload_sha256": digest(obj),
        }
        review["content_sha256"] = content_hash(review)
        reviews.append(review)
        obj["review_ref"] = {
            "id": review["review_id"],
            "version": 1,
            "content_sha256": review["content_sha256"],
        }

    reviewed(entry, "entry")
    entry["content_hash"] = entry_hash(entry)
    binding = {
        "binding_id": "synthetic-binding",
        "registry_release_ref": registry_ref,
        "entry_ref": {
            "id": entry["entry_id"],
            "version": 1,
            "content_sha256": entry["content_hash"],
        },
        "claim_ids": ["synthetic-claim"],
        "subject_class_ids": ["synthetic-subject"],
        "object_scale": "synthetic-whole",
        "otype_scope": ["pA*"],
        "property_bindings": [
            {
                "property_id": definition["property_id"],
                "definition_version": definition["definition_version"],
                "definition_hash": definition["content_sha256"],
            }
        ],
        "required_conditions": [],
        "excluded_conditions": [],
    }
    reviewed(binding, "binding")
    source = {
        "source_id": "synthetic-source",
        "identity": {"title": "SYNTHETIC fixture"},
        "qualification": {"state": "eligible"},
        "evidence": [piece],
    }
    data = {
        "entries": [entry],
        "bindings": [binding],
        "sources": [source],
        "index": {},
        "coverage": {"synthetic": True},
        "reviews": reviews,
    }
    write_package(path, release_id, registry_ref, data)
    return data


def write_package(path, release_id, registry_ref, data):
    path.mkdir(parents=True, exist_ok=True)
    files = []
    for role, body in data.items():
        raw = canonical(body)
        (path / (role + ".json")).write_bytes(raw)
        files.append(
            {"role": role, "path": role + ".json", "sha256": hashlib.sha256(raw).hexdigest()}
        )
    manifest = {
        "schema_version": "insight-knowledge/1",
        "status": "ready_to_import",
        "release_id": release_id,
        "synthetic": True,
        "registry_release_ref": registry_ref,
        "content_files": files,
    }
    manifest["content_sha256"] = content_hash(manifest)
    (path / "manifest.json").write_bytes(canonical(manifest))


def test_knowledge_evidence_and_binding_reviews_are_verified_beyond_file_hashes(tmp_path):
    app = application(tmp_path / "data")
    root = tmp_path / "kb"
    data = package(app, root)
    validated = app.knowledge.validate(root)
    assert len(validated["entries"]) == 1
    data["bindings"][0]["claim_ids"] = ["synthetic-claim", "unreviewed-claim"]
    write_package(root, "synthetic-kb", validated["manifest"]["registry_release_ref"], data)
    with pytest.raises(DomainError) as caught:
        app.knowledge.validate(root)
    assert caught.value.code == "KB_REVIEW_STALE"


def test_explicit_pinned_knowledge_does_not_follow_active_and_revocation_fails_closed(tmp_path):
    app = application(tmp_path / "data")
    package(app, tmp_path / "kb-one", "synthetic-one")
    app.knowledge.import_release(tmp_path / "kb-one")
    first = app.knowledge.load()
    reference = {
        "id": first["manifest"]["release_id"],
        "version": 1,
        "content_sha256": first["manifest"]["content_sha256"],
    }
    package(app, tmp_path / "kb-two", "synthetic-two")
    app.knowledge.import_release(tmp_path / "kb-two")
    assert app.knowledge.load()["manifest"]["release_id"] == "synthetic-two"
    assert app.knowledge.load(reference)["manifest"]["release_id"] == "synthetic-one"
    with app.repository.transaction() as conn:
        conn.execute(
            "INSERT INTO revocations(event_id,release_id,reason,evidence) VALUES(?,?,?,?)",
            (
                "synthetic-revocation",
                "synthetic-one",
                "synthetic test withdrawal",
                canonical({"synthetic": True}),
            ),
        )
    with pytest.raises(DomainError) as caught:
        app.knowledge.load(reference)
    assert caught.value.code == "KB_REVOKED"


def test_delivered_insight_is_pinned_and_data_facts_survive_without_a_model_call(tmp_path):
    async def run():
        app = application(tmp_path / "data")
        package(app, tmp_path / "kb")
        app.knowledge.import_release(tmp_path / "kb")
        state, _ = await confirmed_case(app)
        with app.repository.read() as conn:
            report = app.repository.object(
                conn, state["task_id"], "insight", state["insight_ref"]["id"]
            )
            pins = app.repository.objects(conn, state["task_id"], "insight_knowledge_pin")
            assert pins[0]["reference"] == report["knowledge_release_ref"]
            assert len(report["facts"]) == 1 and len(report["theory"]) == 1
            assert report["status"] == "partial"
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())
