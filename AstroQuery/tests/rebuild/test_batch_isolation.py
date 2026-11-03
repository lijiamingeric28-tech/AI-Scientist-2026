from astroquery_ai.science.extraction import validated_batch
from tests.rebuild.test_catalog_transcription import proposal


def test_malformed_candidate_and_context_do_not_erase_valid_measurement():
    good = proposal().model_dump(mode="json")
    raw = {
        "results": [good, {**good, "value": {"kind": "real", "value": "NaN"}}],
        "coverage": "checked",
        "limitations": [],
        "context_requests": [
            {
                "page": 3,
                "locator": None,
                "property_ids": [good["property_id"]],
                "reason": "Need the cited table header",
            },
            {"unexpected": True},
        ],
    }
    batch, failures = validated_batch(raw)
    assert len(batch.results) == 1 and batch.results[0].raw_value == "26.764100"
    assert len(batch.context_requests) == 1 and batch.context_requests[0].page == 3
    assert batch.coverage == "partial"
    assert {failure["kind"] for failure in failures} == {"result", "context_request"}
    assert raw["coverage"] == "checked" and len(raw["results"]) == 2
