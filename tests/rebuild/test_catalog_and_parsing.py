import asyncio

import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.parsing import Parsers
from astroquery_ai.science.catalogs import (
    exact_identifier,
    exact_rows,
    parse_votable,
    declared_namespace,
    local_identifier,
)


def test_identifier_namespace_and_suffix_are_preserved():
    assert exact_identifier("HD84937") == exact_identifier("HD  84937")
    assert exact_identifier("BD+284211") == exact_identifier("BD+28 4211")
    assert exact_identifier("NGC1234A") != exact_identifier("NGC1234")
    assert exact_identifier("NGC 1234") != exact_identifier("IC 1234")
    assert exact_identifier("GHCG 12") != exact_identifier("LGG 12")
    assert exact_identifier("Gaia DR2 1234") != exact_identifier("Gaia DR3 1234")
    assert exact_identifier("4FGL J1234.1+5678e") != exact_identifier("4FGL J1234.1+5678")
    with pytest.raises(DomainError):
        exact_identifier("1234")


def test_same_identifier_can_have_multiple_observation_rows_but_substrings_do_not_match():
    rows = [{"Name": "NGC1234A"}, {"Name": "NGC 1234"}, {"Name": "NGC 1234"}, {"Name": "IC1234"}]
    assert exact_rows(rows, ["Name"], ["NGC1234"]) == [1, 2]


def test_namespace_requires_column_evidence_and_does_not_cross_gaia_releases():
    namespace = declared_namespace(
        {"name": "Source", "description": "Gaia DR3 source identifier"}, "Gaia DR3"
    )
    rows = [{"Source": "1234567890123456789"}, {"Source": "1234567890123456790"}]
    assert local_identifier("Gaia DR3 1234567890123456789", namespace) == "1234567890123456789"
    assert exact_rows(
        rows, ["Source"], ["Gaia DR3 1234567890123456789"], {"Source": namespace}
    ) == [0]
    assert (
        exact_rows(rows, ["Source"], ["Gaia DR2 1234567890123456789"], {"Source": namespace}) == []
    )
    with pytest.raises(DomainError):
        declared_namespace(
            {"name": "Source", "description": "unidentified source number"}, "Gaia DR3"
        )


def test_pulsar_coordinate_identifier_uses_actual_column_declaration_and_keeps_components():
    column = {'name': 'PSRJ', 'datatype': 'char', 'description': 'Pulsar name based on J2000 coordinates'}
    namespace = declared_namespace(column, None)
    assert namespace == 'PSR'
    assert local_identifier('PSR J0437-4715', namespace) == 'J0437-4715'
    assert local_identifier('PSR J1748-2446ad', namespace) == 'J1748-2446ad'
    rows = [{'PSRJ': 'J0437-4715'}, {'PSRJ': 'J0437-47'}, {'PSRJ': 'J0437-4715A'}, {'PSRJ': 'B0437-4715'}]
    assert exact_rows(rows, ['PSRJ'], ['PSR J0437-4715'], {'PSRJ': namespace}) == [0]
    assert declared_namespace({'name': 'Name', 'description': 'Pulsar name (B name if exists, otherwise the Jname)'}, None) == 'PSR'
    assert declared_namespace({'name': 'Name', 'description': 'Quasar name based on J2000 coordinates'}, None) is None
    assert declared_namespace({'name': 'PSRJ', 'description': 'Unspecified identifier'}, None) is None
    assert local_identifier('PSR candidate_name', namespace) is None


def test_votable_overflow_and_error_are_not_successful_empty_queries():
    xml = b'<VOTABLE><INFO name="QUERY_STATUS" value="OVERFLOW"/><RESOURCE name="SYNTHETIC"><TABLE name="SYNTHETIC/T"><FIELD name="value" datatype="double" unit="m"/></TABLE></RESOURCE></VOTABLE>'
    parsed = parse_votable(xml)
    assert parsed["overflow"] is True and parsed["resources"][0]["tables"][0]["rows"] == []
    with pytest.raises(DomainError) as error:
        parse_votable(xml.replace(b"OVERFLOW", b"ERROR"))
    assert error.value.code == "CATALOG_SERVICE_ERROR"


def test_isolated_pdf_parser_returns_pages_and_actual_image(tmp_path):
    import pymupdf

    path = tmp_path / "fresh-synthetic-parser.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((20, 30), "SYNTHETIC parser case: zero = 0")
        document.save(path)

    async def run():
        parsers = Parsers()
        result = await parsers.run("inspect_pdf", path)
        assert result["page_count"] == 1
        assert "zero = 0" in result["pages"][0]["text"]
        png = await parsers.run("page_image", path, page=1)
        assert png.startswith(b"\x89PNG")

    asyncio.run(run())
