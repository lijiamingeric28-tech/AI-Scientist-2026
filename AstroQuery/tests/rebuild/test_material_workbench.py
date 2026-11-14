from copy import deepcopy

import pytest

from astroquery_ai.application.material_workbench import MaterialIndex, material_overview
from astroquery_ai.query.drafts import _selection_ready, apply_property_choices
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.science.results import research_export, workbench_export
from tests.rebuild.test_research_exports import fixture


def test_catalog_card_opens_saved_data_instead_of_empty_metadata_without_rewriting_source():
    body = fixture()
    source = body['sources'][0]
    source.pop('artifact')
    source.update(kind='catalog', schema_artifact={'artifact_id': 'schema-only'})
    body['evidence_index'][0].update(text_origin='original_cells',
        artifact_ref={'id': 'actual-rows', 'content_sha256': 'c' * 64})
    body['evidence_index'].append({'evidence_id': 'unrelated', 'source_id': 'elsewhere',
        'text_origin': 'original_cells', 'artifact_ref': {'id': 'wrong-source'}})
    before = deepcopy(body)
    material = MaterialIndex(body).materials['s1']
    assert material['artifact']['artifact_id'] == 'actual-rows'
    assert material['schema_artifact']['artifact_id'] == 'schema-only'
    assert [a['artifact_id'] for a in material['data_artifacts']] == ['actual-rows']
    assert body == before


def test_groups_keep_parent_attachment_and_only_evidenced_property_memberships():
    body = fixture()
    body["sources"][0].update(kind="paper", work={"work_id": "w", "records": [{"bibcode": "source-bib"}]})
    body["sources"].extend([
        {"source_id": "table", "kind": "official_attachment", "work_id": "w", "title": "Observed series",
         "association": {"source_table_id": "test/table"}, "artifact": {"artifact_id": "table-file"}},
        {"source_id": "same-table", "kind": "catalog", "title": "Observed series",
         "table_id": "test/table", "artifact": {"artifact_id": "table-file"}},
        {"source_id": "elsewhere", "kind": "catalog", "title": "Unrelated table"},
    ])
    body["measurements"][1]["source_ref"]["id"] = "same-table"
    second = deepcopy(body["definitions"][0])
    second["property_id"] = "second"
    second["definition"]["name_cn"] = "第二项"
    body["definitions"].append(second)
    body["figures"] = [{"figure_id": "fig", "source_id": "s1", "property_ids": ["second"]}]
    index = MaterialIndex(body)
    first, = index.listing(property_id="p-temperature", output="data", kind="official_attachment")
    image, = index.listing(property_id="second", output="figures")
    other, = index.listing(property_id="other", output="none")
    assert first["group_id"] == image["group_id"] == "s1"
    assert first["record_count"] == 2 and image["figure_count"] == 1
    assert first["body_record_count"] == 1
    assert first["attachments"][0]["record_count"] == 1
    group, pid = index.resolve("table", "p-temperature")
    assert index.record_ids(group, pid, "main") == ["m1"]
    assert index.record_ids(group, pid, "table") == ["m2"]
    with pytest.raises(DomainError):
        index.record_ids(group, pid, "elsewhere")
    assert index.groups["s1"]["by_property"]["p-temperature"]["records"] == ["m1", "m2"]
    assert other["group_id"] == "elsewhere"


def test_material_count_includes_read_sources_without_extraction_and_respects_saved_report():
    body = fixture()
    body["sources"].extend([
        {"source_id": "read", "kind": "catalog", "readme": {"text": "Measured target and band"}},
        {"source_id": "other", "kind": "catalog", "readme": {"text": "No saved property relationship"}},
    ])
    body["coverage"] = [{"source_id": "read", "property_id": "p-temperature"}]
    index = MaterialIndex(body)
    assert index.listing(property_id="p-temperature")[0]["record_count"] == 2
    zero, = index.listing(property_id="p-temperature", output="none")
    assert zero["group_id"] == "read"
    assert material_overview(body, index)["total"] == 2
    body["insight_report"] = {"schema_version": "MaterialSummaryReport/1", "status": "partial",
                              "counts": {"p-temperature": {"requested": 2, "ready": 1, "failed": 1}}}
    overview = material_overview(body)
    assert overview["total"] == 2
    assert overview["properties"][0]["ready"] == overview["properties"][0]["failed"] == 1


def test_export_scope_keeps_native_uncertainty_units_and_exact_ids():
    body = fixture()
    body["status"] = "completed"
    body["sources"].append({"source_id": "unselected", "kind": "catalog"})
    body["measurements"][1]["source_ref"]["id"] = "unselected"
    body["evidence_index"][0].update(text_origin="original_cells", raw_text=canonical({
        "cells": {"MJD": "56679.4377", "Filt": "UVW2"},
        "columns": [{"name": "MJD", "unit_text": "d", "description": "Modified Julian Date", "ucd": "time.epoch"},
                    {"name": "Filt", "description": "Swift/UVOT filter", "ucd": "meta.note"}],
    }).decode())
    index = MaterialIndex(body)
    subset = workbench_export._scope(body, index, {"m1"}, set(), "task", "http://127.0.0.1:8800")
    rows, errors, locations = research_export.tables(subset)
    assert [item["measurement_id"] for item in rows] == ["m1"]
    assert rows[0]["export_schema_version"] == 3
    assert (rows[0]["native_epoch"], rows[0]["native_epoch_definition"], rows[0]["native_band"]) == (
        "56679.4377", "Modified Julian Date", "UVW2")
    assert errors[0]["source_unit"] == "K"
    assert errors[0]["source_component"]["values"] == {"minus": "56", "plus": "61"}
    assert locations[0]["locations"][0]["page"] == 10
    assert [item["source_id"] for item in subset["sources"]] == ["s1"]


def test_full_catalog_explicit_selection_is_bound_to_target_and_keeps_omission():
    draft = {
        "target": {"target_id": "verified"}, "registry_release": {"id": "registry"},
        "property_support": {"support_hash": "scope", "bindings": [{"property_id": "p1"}, {"property_id": "p2"}]},
        "property_selection_policy": "model-candidates/1", "selected_property_ids": [], "property_requests": [],
        "model_property_selection": {"candidate_property_ids": ["p1"]},
        "issues": [{"status": "open", "kind": "property_selection_incomplete"},
                   {"status": "open", "kind": "unsupported_unit"}],
    }
    with pytest.raises(DomainError):
        apply_property_choices(draft, ["p2"], "action")
    apply_property_choices(draft, ["p2"], "action", full_catalog=True)
    assert _selection_ready(draft)
    assert [item["status"] for item in draft["issues"]] == ["resolved", "open"]
    draft["target"]["target_id"] = "other"
    assert not _selection_ready(draft)


def test_zip_source_index_resolves_the_actual_originals(tmp_path):
    from io import BytesIO
    import json
    from types import SimpleNamespace
    from zipfile import ZipFile

    body = fixture()
    body["status"] = "completed"
    body["sources"][0]["readme"] = {"artifact": {"artifact_id": "readme1"}}
    index = MaterialIndex(body)
    data = workbench_export._scope(body, index, {"m1"}, set(), "task", "http://127.0.0.1:8800")
    data["material_summaries"] = []
    originals = {
        "pdf1": ("application/pdf", b"%PDF-1.7\n", "原件/Example.pdf"),
        "readme1": ("text/plain", b"Original column notes\n", "原件/ReadMe.txt"),
    }
    for aid, (_, content, _) in originals.items():
        (tmp_path / aid).write_bytes(content)

    artifacts = SimpleNamespace(lease=lambda owner, aid: aid, release=lambda lease: None,
                                read_owned=lambda owner, aid: ({"media_type": originals[aid][0]}, tmp_path / aid))
    files = [{"kind": "original", "path": info[2], "artifact_id": aid}
             for aid, info in originals.items()]
    files.extend([{"kind": "sources", "path": "来源与定位.json"},
                  {"kind": "data", "path": "数据/测量.csv", "measurement_ids": ["m1"]}])
    zip_bytes, media = workbench_export._build(SimpleNamespace(artifacts=artifacts), "task", data,
                                               files, {"data_format": "csv", "container": "zip"})
    assert media == "application/zip"
    with ZipFile(BytesIO(zip_bytes)) as archive:
        source_index = json.loads(archive.read("来源与定位.json"))
        source, = source_index["sources"]
        assert source["original_in_package"] is True
        assert archive.read(source["original_paths"]["primary"]) == originals["pdf1"][1]
        assert archive.read(source["original_paths"]["readme"]) == originals["readme1"][1]
        locator, = source_index["locations"][0]["locations"]
        assert locator["original_path"] == source["original_paths"]["primary"]
        assert locator["original_url"].endswith("/pdf1#page=10")
        assert b"original_path" in archive.read("数据/测量.csv")


@pytest.mark.parametrize("publish_failure", [False, True])
def test_summary_job_closes_atomically_with_its_final_delivery(tmp_path, monkeypatch, publish_failure):
    import asyncio
    from types import SimpleNamespace

    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.science import material_summaries

    repo = Repository(tmp_path / "runtime.sqlite3")
    task_id = repo.create_task("summary completion regression")["task_id"]
    delivery = {"delivery_id": "delivery", "snapshot_ref": {"id": "snapshot"}}
    with repo.transaction() as conn:
        repo.mutate_task(conn, task_id, lifecycle="queued", science_state="sealed")
        repo.enqueue(conn, task_id, "M11", "insights", {"delivery_id": "delivery"})
    job = repo.claim_job("summary-completion-test", task_id=task_id)
    assert job["kind"] == "insights"
    monkeypatch.setattr(material_summaries, "_inputs", lambda *args: (SimpleNamespace(entries=[], groups={}), None))

    def publish(conn, tid, report):
        assert report["status"] == "generated"
        assert conn.execute("SELECT status FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0] == "succeeded"
        if publish_failure:
            raise DomainError("TEST_PUBLISH_FAILURE", "Test finalization rolled back")
        repo.mutate_task(conn, tid, lifecycle="completed")

    app = SimpleNamespace(delivery=SimpleNamespace(read_for_display=lambda *args: delivery, finish_insights=publish))
    service = SimpleNamespace(repo=repo, app=app)
    if publish_failure:
        with pytest.raises(DomainError, match="rolled back"):
            asyncio.run(material_summaries.generate(service, job, {}))
    else:
        asyncio.run(material_summaries.generate(service, job, {}))
    with repo.read() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0] == (
            "running" if publish_failure else "succeeded"
        )
    assert repo.get_task(task_id)["lifecycle"] == ("running" if publish_failure else "completed")
