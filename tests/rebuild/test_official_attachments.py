"""Official relationship, immutable local cells and independent body quota."""

import asyncio

import httpx
import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.attachments import official_links, structured_table, acquired_format
from tests.rebuild.scenario import application, confirmed_case
from tests.rebuild.test_new_end_to_end import XML_HEADER


LANDING = b"""<html><meta name="citation_doi" content="10.1234/synthetic-attachment">
<a href="unrelated.csv">Unrelated</a><section class="supplementary-material"><br></br>
<a href="values.csv">Table</a><a href="extra.pdf">PDF</a></section><a href="outside.csv">Outside</a></html>"""


def test_exact_parent_and_supplement_scope_are_both_required():
    links, rejected = official_links(
        LANDING, "https://publisher.example/article", ["10.1234/synthetic-attachment"]
    )
    assert [item["url"] for item in links] == ["https://publisher.example/values.csv", "https://publisher.example/extra.pdf"]
    assert links[1]['format'] == 'pdf' and links[1]['association']['parent_dois'] == ['10.1234/synthetic-attachment']
    with pytest.raises(DomainError, match="DOI"):
        official_links(LANDING, "https://publisher.example/article", ["10.1234/different"])


def test_actual_links_nearby_text_and_metadata_handle_unmarked_downloads():
    html = b'''<html><meta name="citation_doi" content="10.1234/synthetic-attachment">
    <meta name="citation_data_url" content="https://archive.example/data/42">
    <p>Machine-readable table for this article: <a href="table.csv">Download</a></p>
    <a href="/fetch?id=3">Supporting information</a>
    <a href="neighbor.csv">Another publication</a></html>'''
    links, gaps = official_links(html, 'https://publisher.example/article', ['10.1234/synthetic-attachment'])
    assert {l['url'] for l in links} == {'https://archive.example/data/42',
        'https://publisher.example/table.csv', 'https://publisher.example/fetch?id=3'}
    assert any(g['url'].endswith('neighbor.csv') and g['reason'] == 'candidate_association_unresolved' for g in gaps)
    pending = next(l for l in links if l['url'].endswith('id=3'))
    assert pending['format'] == 'pending'
    assert acquired_format(b'Name,Value\nSYNTHETIC,1\n', pending, {'media_type': 'text/csv; charset=utf-8'}) == 'csv'
    assert acquired_format(b'<VOTABLE></VOTABLE>', pending, {}) == 'votable'
    for raw in [b'<html>sign in</html>', b'not a declared structured table']:
        with pytest.raises(DomainError) as caught:
            acquired_format(raw, pending, {})
        assert caught.value.code == 'ATTACHMENT_ACTUAL_FORMAT'
    assert acquired_format(b'%PDF-1.7', pending, {}) == 'pdf'


def test_csv_preserves_long_identifiers_separate_errors_and_actual_row_location(tmp_path):
    path = tmp_path / "official.csv"
    path.write_text(
        "Source,Value,Stat,Sys\n1234567890123456790,2,.1,.2\n1234567890123456789,0,.03,.04\n",
        encoding="utf-8",
    )
    header = structured_table(path, "csv", "table", header_only=True)
    assert header["total_rows"] is None
    result = structured_table(
        path,
        "csv",
        "table",
        id_column="Source",
        namespace="Gaia DR3",
        aliases=["Gaia DR3 1234567890123456789"],
    )
    table = result["resources"][0]["tables"][0]
    assert table["source_row_numbers"] == [1]
    assert table["rows"] == [
        {"Source": "1234567890123456789", "Value": "0", "Stat": ".03", "Sys": ".04"}
    ]
    assert (
        structured_table(
            path,
            "csv",
            "table",
            id_column="Source",
            namespace="Gaia DR3",
            aliases=["Gaia DR2 1234567890123456789"],
        )["resources"][0]["tables"][0]["rows"]
        == []
    )


def test_truncated_rows_and_overflow_are_explicit(tmp_path):
    path = tmp_path / "broken.csv"
    path.write_text("Name,Value\nHD 1\n", encoding="utf-8")
    with pytest.raises(DomainError) as caught:
        structured_table(path, "csv", "table")
    assert caught.value.code == "ATTACHMENT_ROW_SHAPE"
    path.write_text("Name,Value\nHD 1,0\nHD 1,1\n", encoding="utf-8")
    result = structured_table(path, "csv", "table", maximum_rows=1)
    assert result["overflow"] is True and result["total_rows"] == 2


def test_candidate_navigation_survives_isolated_parser_and_preserves_source_rows(tmp_path):
    import asyncio
    from astroquery_ai.runtime.parsing import Parsers
    path = tmp_path / 'SYNTHETIC candidates.csv'
    path.write_text('Name,Value\nUnrelated,0\n1234 + 5678 A,1.00\nB1234+5678B,2.00\n', encoding='utf-8')

    async def run():
        return await Parsers().run('structured_table', path, format='csv', table_id='SYNTHETIC/table',
            id_column='Name', candidate_patterns=['*1234*5678*'])
    result = asyncio.run(run())
    table = result['resources'][0]['tables'][0]
    assert table['source_row_numbers'] == [1, 2]
    assert [r['Name'] for r in table['rows']] == ['1234 + 5678 A', 'B1234+5678B']
    # Both frames/components remain candidates. Parsing grants no identity.
    assert result['overflow'] is False


def test_cds_ascii_uses_the_associated_readme_for_filename_units_and_column_definitions(tmp_path):
    path = tmp_path / "content-hash-without-original-name"
    path.write_text(f"{'HD 1':5s} {0.0:4.1f}\n", encoding="utf-8")
    readme = """SYNTHETIC fixture only
Byte-by-byte Description of file: measurements.dat
------------------------------------------------------------
   Bytes Format Units Label Explanations
------------------------------------------------------------
   1- 5  A5     ---   Name  Full object identifier
   7-10  F4.1   km    Length Synthetic whole length
------------------------------------------------------------
"""
    result = structured_table(
        path, "mrt", "table", readme_text=readme, original_filename="measurements.dat"
    )
    table = result["resources"][0]["tables"][0]
    assert table["columns"][1]["unit_text"] == "km"
    assert table["rows"] == [{"Name": "HD 1", "Length": "0.0"}]
    with pytest.raises(Exception):
        structured_table(path, "mrt", "table", readme_text=readme, original_filename="wrong.dat")


def test_fits_units_and_missing_values_are_preserved(tmp_path):
    from astropy.table import Table, MaskedColumn

    table = Table({"Name": ["HD 1", "HD 2"]})
    table["Value"] = MaskedColumn([0.0, 1.0], mask=[False, True], unit="km")
    path = tmp_path / "official.fits"
    table.write(path)
    result = structured_table(path, "fits", "table")
    actual = result["resources"][0]["tables"][0]
    assert actual["columns"][1]["unit_text"] == "km"
    # FITS represents missing floating cells as NaN; they must not become a value.
    assert actual["rows"][0]["Value"] == "0.0"
    assert actual["rows"][1]["Value"] == ""


def test_votable_allows_optional_names_only_with_local_artifact_table_identity(tmp_path):
    path = tmp_path / "unnamed.vot"
    path.write_bytes(
        b'<VOTABLE><RESOURCE><TABLE><FIELD name="Name" datatype="char"/><FIELD name="Value" datatype="double" unit="m"/><DATA><TABLEDATA><TR><TD>HD 1</TD><TD>0</TD></TR></TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>'
    )
    result = structured_table(path, "votable", "verified-local-table")
    table = result["resources"][0]["tables"][0]
    assert table["table_id"] == "verified-local-table" and table["rows"][0]["Value"] == "0"
    path.write_bytes(path.read_bytes().replace(b'name="Value"', b'name="Name"'))
    with pytest.raises(DomainError) as caught:
        structured_table(path, "votable", "verified-local-table")
    assert caught.value.code == "VOTABLE_COLUMNS"


def test_failed_parent_does_not_discover_supplements_or_replace_selection(
    tmp_path,
):
    async def run():
        app = application(tmp_path / "data")

        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404, text='SYNTHETIC: no ReadMe')
            if request.url.host == "api.adsabs.harvard.edu":
                doc = {
                    "bibcode": "SYNTHETIC2026A",
                    "doctype": "article",
                    "title": ["SYNTHETIC fixture only"],
                    "doi": ["10.1234/synthetic-attachment"],
                }
                return httpx.Response(200, json={"response": {"numFound": 1, "docs": [doc]}})
            if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
                return httpx.Response(200, content=XML_HEADER + b"</TABLE></RESOURCE></VOTABLE>")
            if request.url.host == "doi.org":
                return httpx.Response(
                    302, headers={"location": "https://publisher.example/article"}
                )
            if request.url.host == "publisher.example":
                return httpx.Response(
                    200,
                    content=LANDING
                    if request.url.path == "/article"
                    else b"Name,Length\nOTHER,9\nSYNTHETIC_AQ,0\n",
                )
            raise AssertionError("Unregistered network in synthetic test")

        app.http.transport = httpx.MockTransport(handle)
        state, _ = await confirmed_case(app)
        assert state["lifecycle"] == "completed"
        tid = state["task_id"]
        with app.repository.read() as conn:
            ledger = app.repository.objects(conn, tid, "read_ledger")[0]
            assert len(ledger["selections"]) == 1
            assert list(ledger["selections"].values())[0]["state"] == "released"
            sources = app.repository.objects(conn, tid, "source")
            assert len(sources) == 1 and sources[0]['kind'] == 'catalog'
            measurements = app.repository.objects(conn, tid, "measurement")
            assert measurements == []
            assert not app.repository.objects(conn, tid, 'attachment')
            assert not conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='attachment_discover'", (tid,)).fetchone()
            zero_source = next(source for source in sources if source["kind"] == "catalog")
            assert all(
                record["source_ref"]["id"] != zero_source["source_id"] for record in measurements
            )
            assert zero_source["schema_artifact"]["artifact_id"]
            evidence = app.repository.objects(conn, tid, "evidence")
            assert not any(item['locator'].get('row') == 1 for item in evidence)
            assert all(
                row["state"] == "closed"
                for row in conn.execute("SELECT state FROM producers WHERE task_id=?", (tid,))
            )
            assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0

    asyncio.run(run())
