from astroquery_ai.runtime.paths import knowledge_content_root
"""Actual received content compatibility, not a test of scientific correctness."""

import hashlib
from pathlib import Path

import pytest

from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.knowledge_content import KnowledgeContent, payload_hash
from astroquery_ai.science.prompt_contracts import scientific_view

ROOT = knowledge_content_root()


def test_received_content_preserves_claim_level_basis_and_literal_star_scope():
    reader = KnowledgeContent()
    content = reader.load(ROOT)
    assert content["report"]["entries"] == 166 and content["report"]["claims"] == 600
    assert content["report"]["source_verified_claims"] == 17
    assert content["report"]["author_knowledge_claims"] == 583
    psr = reader.preview(content, "Psr")
    stars = reader.preview(content, "*")
    assert psr["runtime_authorized"] is False and psr["target_applicability"] == "not_established"
    assert all("*" in entry["otype_scope"] for entry in stars["entries"])
    exclusive = {entry["entry_id"] for entry in psr["entries"] if entry["otype_scope"] == ["Psr"]}
    assert exclusive and not exclusive.intersection(entry["entry_id"] for entry in stars["entries"])
    for entry in psr["entries"]:
        assert entry["conditions_zh"] and entry["limitations_zh"] and entry["uncertainty_notes"]
        for claim in entry["claims"]:
            if claim["authoring_basis"] == "source_verified":
                assert claim["source_evidence"] and claim["basis_label"] == "来源已核查"
    with pytest.raises(DomainError):
        reader.preview(content, "Psr*")


def test_cannot_relabel_author_claim_as_verified_even_with_recomputed_container_hashes(tmp_path):
    manifest = loads((ROOT / "content-manifest.json").read_bytes())
    for relative in manifest["files"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    entries = loads((tmp_path / "content/entries.json").read_bytes())
    claim = next(
        claim for claim in entries[0]["claims"] if claim["authoring_basis"] == "author_knowledge"
    )
    claim["authoring_basis"] = "source_verified"
    entries[0]["content_hash"] = payload_hash(entries[0])
    reviews = loads((tmp_path / "content/reviews.json").read_bytes())
    next(review for review in reviews if review["review_id"] == entries[0]["review_id"])[
        "entry_ref"
    ]["content_hash"] = entries[0]["content_hash"]
    for relative, body in [("content/entries.json", entries), ("content/reviews.json", reviews)]:
        raw = canonical(body)
        (tmp_path / relative).write_bytes(raw)
        manifest["files"][relative]["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["content_hash"] = payload_hash(manifest)
    (tmp_path / "content-manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(DomainError) as caught:
        KnowledgeContent().load(tmp_path)
    assert caught.value.code == "KNOWLEDGE_VERIFIED_WITHOUT_EVIDENCE"


def test_prompt_view_drops_audit_linkage_but_keeps_complete_scientific_conditions():
    original = {
        "definition": {
            "description": "long context " * 500,
            "evidence_refs": [{"id": "e"}],
            "measurement_conditions_schema": [
                {
                    "key": "source_Units",
                    "description": "TCB或TDB逐行保留",
                    "required": True,
                    "evidence_refs": [{"id": "proof"}],
                }
            ],
        },
        "output_profile": {"unit": "s"},
    }
    view = scientific_view(original)
    assert view["definition"]["description"] == original["definition"]["description"]
    assert view["definition"]["measurement_conditions_schema"] == [
        {"key": "source_Units", "description": "TCB或TDB逐行保留", "required": True}
    ]
    assert original["definition"]["evidence_refs"] == [{"id": "e"}]
