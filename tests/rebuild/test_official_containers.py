import asyncio
import io
import zipfile

import httpx

from astroquery_ai.science.archives import structured_archive
from tests.rebuild.scenario import application, confirmed_case
from tests.rebuild.test_new_end_to_end import XML_HEADER


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return output.getvalue()


def test_container_hashes_files_and_lists_supplement_pdf_without_parsing_or_running_code(tmp_path):
    path = tmp_path / "synthetic.zip"
    path.write_bytes(
        zip_bytes(
            [
                ("data/table.csv", b"Name,value\nSYNTHETIC,0\n"),
                ("data/ReadMe", b"SYNTHETIC ReadMe"),
                ("code.py", b'raise RuntimeError("NEVER EXECUTE")'),
                ("supplement.pdf", b"%PDF-SYNTHETIC"),
            ]
        )
    )
    result = structured_archive(path, original_filename=path.name)
    assert result["state"] == "enumerated" and result["code_executed"] is False
    assert all(entry["sha256"] for entry in result["entries"])
    assert [item["path"] for item in result["members"]] == ["data/table.csv", "data/ReadMe", "supplement.pdf"]
    assert (
        next(item for item in result["entries"] if item["path"].endswith(".pdf"))["role"]
        == "supplementary_pdf"
    )
    assert not (tmp_path / "data").exists()


def test_container_unsafe_paths_and_expansion_bomb_leave_partial_manifest(tmp_path):
    path = tmp_path / "bounded.zip"
    path.write_bytes(
        zip_bytes(
            [
                ("../escape.csv", b"bad"),
                ("C:/bad.csv", b"bad"),
                ("a/CON.csv", b"bad"),
                ("good.csv", b"SYNTHETIC,0"),
                ("huge.csv", b"0" * (32 * 1024**2 + 1)),
            ]
        )
    )
    result = structured_archive(path, original_filename=path.name)
    assert result["state"] == "partial"
    assert len([item for item in result["entries"] if item["state"] == "rejected"]) == 3
    assert result["expanded_bytes"] < 32 * 1024**2
    assert [item["path"] for item in result["members"]] == ["good.csv"]
    assert any(item["reason"] == "archive_expanded_byte_limit" for item in result["gaps"])


def test_nested_container_limit_and_duplicate_member_are_explicit_gaps(tmp_path):
    path = tmp_path / "nested.zip"
    inner = zip_bytes([("table.csv", b"Name,value\nSYNTHETIC,0")])
    middle = zip_bytes([("deep.zip", inner), ("Table.csv", b"first"), ("table.csv", b"second")])
    path.write_bytes(zip_bytes([("middle.zip", middle)]))
    result = structured_archive(path, original_filename=path.name)
    assert {item["reason"] for item in result["gaps"]} == {
        "archive_nesting_limit",
        "duplicate_member_name",
    }
    assert not any(
        item["parent_chain"] and len(item["parent_chain"]) > 1 and item["format"] == "csv"
        for item in result["members"]
    )


def test_tar_gzip_two_levels_and_link_rejection(tmp_path):
    import gzip
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        data = b"Name,value\nSYNTHETIC,0\n"
        info = tarfile.TarInfo("table.csv")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("link.csv")
        link.type, link.linkname = tarfile.SYMTYPE, "../outside"
        archive.addfile(link)
    path = tmp_path / "tables.tar.gz"
    path.write_bytes(gzip.compress(buffer.getvalue()))
    result = structured_archive(path, original_filename=path.name)
    assert any(
        item["path"] == "table.csv" and item["format"] == "csv" for item in result["members"]
    )
    assert any(item["reason"] == "linked_or_special_member" for item in result["gaps"])


def test_official_zip_reaches_same_catalog_extractor_without_body_read_grant(tmp_path):
    async def run():
        app = application(tmp_path)
        bundle = zip_bytes(
            [
                ("data/table.csv", b"Name,Length\nOTHER,9\nSYNTHETIC_AQ,0\n"),
                ("analysis.py", b'raise RuntimeError("NEVER EXECUTE")'),
                ("supplement.pdf", b"%PDF-SYNTHETIC"),
            ]
        )

        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404, text='SYNTHETIC: no ReadMe')
            if request.url.host == "api.adsabs.harvard.edu":
                return httpx.Response(
                    200,
                    json={
                        "response": {
                            "numFound": 1,
                            "docs": [
                                {
                                    "bibcode": "SYNTHETICZIP2026",
                                    "doctype": "article",
                                    "title": ["SYNTHETIC official ZIP fixture only"],
                                    "doi": ["10.1234/synthetic-zip"],
                                }
                            ],
                        }
                    },
                )
            if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
                return httpx.Response(200, content=XML_HEADER + b"</TABLE></RESOURCE></VOTABLE>")
            if request.url.host == "doi.org":
                return httpx.Response(
                    302, headers={"location": "https://publisher.example/article"}
                )
            if request.url.host == "publisher.example":
                return httpx.Response(
                    200,
                    content=bundle
                    if request.url.path.endswith(".zip")
                    else b'<meta name="citation_doi" content="10.1234/synthetic-zip"><section class="supplement"><a href="data.zip">Data</a></section>',
                )
            raise AssertionError("Unregistered synthetic HTTP")

        app.http.transport = httpx.MockTransport(handle)
        from tests.rebuild.scenario import synthetic_acquired_parent
        state, _ = await confirmed_case(app, setup_scheduler=synthetic_acquired_parent)
        assert state["lifecycle"] == "completed"
        with app.repository.read() as conn:
            attachments = app.repository.objects(conn, state["task_id"], "attachment")
            assert len(attachments) == 1 and attachments[0]["original_filename"] == "table.csv"
            assert attachments[0]["association"]["member_path"] == "data/table.csv"
            assert (
                app.repository.objects(conn, state["task_id"], "container_manifest")[0][
                    "code_executed"
                ]
                is False
            )
            record = app.repository.objects(conn, state["task_id"], "measurement")[0]
            assert record["raw_value"] == "0"
            ledger = app.repository.objects(conn, state["task_id"], "read_ledger")[0]
            assert all(
                selection["state"] == "reserved" for selection in ledger["selections"].values()
            )
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())
