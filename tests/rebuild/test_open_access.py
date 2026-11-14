import asyncio

import httpx
import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.open_access import doi_locations
from tests.rebuild.scenario import application, confirmed_case
from tests.rebuild.test_new_end_to_end import XML_HEADER


def test_unpaywall_doi_identity_and_version_hint_do_not_certify_pdf():
    result = doi_locations(
        {
            "doi": "10.1234/SYNTHETIC",
            "oa_locations": [
                {"url_for_pdf": None, "url": "https://example.test/landing"},
                {"url_for_pdf": "https://example.test/preprint", "version": "submittedVersion"},
                {"url_for_pdf": "https://example.test/published", "version": "publishedVersion"},
            ],
        },
        "10.1234/synthetic",
    )
    assert [item["url"] for item in result] == [
        "https://example.test/published",
        "https://example.test/preprint",
    ]
    assert all(
        not item["actual_version_grade_verified"] and not item["manuscript_identity_verified"]
        for item in result
    )
    with pytest.raises(DomainError, match="DOI"):
        doi_locations({"doi": "10.1234/another", "oa_locations": []}, "10.1234/synthetic")


def test_actual_acquisition_uses_open_access_pdf_and_rechecks_unknown_version(tmp_path):
    async def run():
        import pymupdf
        from tests.rebuild.scenario import ScenarioModels

        app = application(tmp_path)
        app.configuration.runtime["unpaywall_email"] = "synthetic@example.test"

        class Models(ScenarioModels):
            async def json(self, *, owner, **kwargs):
                if owner == "M06":
                    return {
                        "results": [],
                        "coverage": "checked",
                        "limitations": ["SYNTHETIC fixture has no scientific measurements."],
                    }, {"attempt_id": "synthetic", "usage": None}
                return await super().json(owner=owner, **kwargs)

        app.models = Models()
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (30, 40),
                "Synthetic new software open access identity example\nDOI: 10.1234/synthetic-oa",
            )
            pdf = doc.tobytes()
        urls = []

        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr', 'vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404, text='SYNTHETIC: no ReadMe')
            urls.append(request.url.host + request.url.path)
            if request.url.host == "api.adsabs.harvard.edu":
                return httpx.Response(
                    200,
                    json={
                        "response": {
                            "numFound": 1,
                            "docs": [
                                {
                                    "bibcode": "SYNTHETIC2026OA",
                                    "doctype": "article",
                                    "title": [
                                        "Synthetic new software open access identity example"
                                    ],
                                    "doi": ["10.1234/synthetic-oa"],
                                }
                            ],
                        }
                    },
                )
            if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
                return httpx.Response(200, content=XML_HEADER + b"</TABLE></RESOURCE></VOTABLE>")
            if request.url.host == "api.unpaywall.org":
                assert request.url.params["email"] == "synthetic@example.test"
                return httpx.Response(
                    200,
                    json={
                        "doi": "10.1234/synthetic-oa",
                        "oa_locations": [
                            {
                                "url_for_pdf": "https://publisher.example/real.pdf",
                                "version": "publishedVersion",
                            }
                        ],
                    },
                )
            if request.url.host == "publisher.example":
                return httpx.Response(200, content=pdf)
            if request.url.host == "doi.org":
                return httpx.Response(
                    200, text='<meta name="citation_doi" content="10.1234/synthetic-oa">'
                )
            raise AssertionError("Unregistered request")

        app.http.transport = httpx.MockTransport(handle)
        state, _ = await confirmed_case(app)
        assert state["lifecycle"] == "completed"
        with app.repository.read() as conn:
            sources = app.repository.objects(conn, state["task_id"], "source")
            paper = next(source for source in sources if source["kind"] == "paper")
            assert paper["version_grade"] == "unknown"  # provider label cannot promote it
            assert paper["identity"]["state"] == "verified"
            assert (
                app.repository.objects(conn, state["task_id"], "open_access_lookup")[0]["state"]
                == "checked"
            )
            assert "synthetic@example.test" not in str(
                [dict(row) for row in conn.execute("SELECT * FROM http_attempts")]
            )
        assert urls.count("api.unpaywall.org/v2/10.1234/synthetic-oa") == 1

    asyncio.run(run())
