from dataclasses import asdict

import pytest

from astroquery_ai.runtime.codec import digest, canonical, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.reviews import ReviewService, ReviewAnswer
from astroquery_ai.science.literature import (
    FairReadLedger,
    compile_queries,
    deduplicate,
    parse_record,
    ranked_queues,
    normalize_arxiv,
    normalize_doi,
)


def test_query_compiler_keeps_both_object_and_property_constraints_and_escapes():
    queries = compile_queries(
        ['SYNTHETIC "object" OR *:*'],
        [
            {
                "family_id": "f",
                "search_concepts": ["x) OR doctype:*"],
                "selected_property_ids": ["p"],
            }
        ],
    )
    assert len(queries) == 2
    for query in queries:
        assert "doctype:(article OR eprint)" in query["query"]
        assert '\\"object\\"' in query["query"]
        assert query["selected_property_ids"] == ["p"]
        assert query["family_id"] == "f"


def test_reliable_identifiers_merge_versions_but_title_similarity_does_not():
    docs = [
        {
            "bibcode": "syn-a",
            "doctype": "article",
            "doi": ["https://doi.org/10.1234/SYNTHETIC"],
            "title": ["same title"],
        },
        {
            "bibcode": "syn-b",
            "doctype": "eprint",
            "doi": ["10.1234/synthetic"],
            "identifier": ["arXiv:2601.00001v2"],
        },
        {"bibcode": "syn-c", "doctype": "article", "title": ["same title"]},
    ]
    works, mapping = deduplicate(list(map(parse_record, docs)))
    assert len(works) == 2
    assert mapping["syn-a"] == mapping["syn-b"] != mapping["syn-c"]
    assert normalize_doi("DOI:10.1234/SYNTHETIC") == "10.1234/synthetic"
    assert normalize_arxiv("astro-ph/0101234v3") == ("astro-ph/0101234", 3)


def test_split_preprint_does_not_merge_distinct_published_works():
    records = [
        parse_record(
            {
                "bibcode": "syn-" + str(i),
                "doctype": "article",
                "doi": [f"10.1234/split-{i}"],
                "identifier": ["arXiv:2601.00002v1"],
            }
        )
        for i in range(2)
    ]
    works, mapping = deduplicate(records)
    assert len(works) == 2


def test_multiple_query_hits_do_not_accumulate_extra_ranking_votes():
    records = [
        parse_record({"bibcode": "syn-a", "doctype": "article"}),
        parse_record({"bibcode": "syn-b", "doctype": "article"}),
    ]
    works, mapping = deduplicate(records)
    query = {
        "family_id": "f",
        "layer": "metadata",
        "selected_property_ids": ["p"],
        "bibcodes": ["syn-a", "syn-a", "syn-b"],
    }
    first = ranked_queues(works, mapping, [query], ["f"])
    assert ranked_queues(works, mapping, [query] * 20, ["f"]) == first


def test_failed_family_does_not_monopolize_read_attempt_pool():
    families = list("ABCDE")
    queues = {family: [f"{family}-{i}" for i in range(30)] for family in families}
    work_families = {wid: [family] for family, works in queues.items() for wid in works}
    ledger = FairReadLedger(families, queues, work_families)
    first_round = []
    for _ in range(5):
        selected = ledger.select()
        first_round.append(selected["sponsor"])
        if selected["sponsor"] == "A":
            ledger.preflight_failed(selected["work_id"])
        else:
            ledger.consume(selected["work_id"])
    assert first_round == families
    assert ledger.credited == {"B": 1, "C": 1, "D": 1, "E": 1}
    restored = FairReadLedger(**loads(canonical(asdict(ledger))))
    assert restored.round_id == 1
    assert restored.select()["round_id"] == 2


def test_forty_consumed_read_slots_are_never_refunded():
    queues = {"f": ["w" + str(i) for i in range(100)]}
    ledger = FairReadLedger(["f"], queues, {wid: ["f"] for wid in queues["f"]})
    for _ in range(40):
        selected = ledger.select()
        ledger.consume(selected["work_id"], unknown=True)
    assert ledger.select() is None
    with pytest.raises(DomainError):
        ledger.preflight_failed("w0")
    assert len(ledger.selections) == 40


def test_eighty_attempts_cap_and_multi_family_work_uses_one_slot():
    ledger = FairReadLedger(["a", "b"], {"a": ["shared"], "b": ["shared"]}, {"shared": ["a", "b"]})
    assert ledger.select()["families"] == ["a", "b"]
    assert len(ledger.selections) == 1 and ledger.served == ["a", "b"]
    ledger = FairReadLedger(
        ["a"], {"a": [str(i) for i in range(100)]}, {str(i): ["a"] for i in range(100)}, maximum_attempts=80
    )
    for _ in range(80):
        selected = ledger.select()
        ledger.preflight_failed(selected["work_id"])
    assert ledger.select() is None


def test_normal_candidate_acquisition_has_no_eighty_attempt_cutoff():
    ledger = FairReadLedger(["a"], {"a": list(map(str, range(100)))},
                            {str(i): ["a"] for i in range(100)})
    for _ in range(100):
        selected = ledger.select()
        ledger.preflight_failed(selected['work_id'])
    assert ledger.select() is None
    assert len(ledger.selections) == 100


@pytest.fixture
def review_case(tmp_path):
    repo = Repository(tmp_path / "reviews.sqlite3")
    task = repo.create_task("SYNTHETIC review case")
    service = ReviewService(repo)
    with repo.transaction() as conn:
        repo.mutate_task(conn, task["task_id"], lifecycle="running", science_state="open")
        evidence_ref = repo.put_object(
            conn,
            task["task_id"],
            "evidence",
            "synthetic-evidence",
            1,
            {"raw_text": "SYNTHETIC: object A has value 1"},
        )
        item = service.register(
            conn,
            task["task_id"],
            {
                "origin": "M06",
                "owner": "M06",
                "issue_kind": "value_transcription",
                "question": "原件中该已选量是否为1？",
                "impact": "controls admission",
                "issue_key": "synthetic-transcription",
                "scope": {"measurement_ids": ["m1"]},
                "basis": {"source_hash": digest("synthetic")},
                "evidence_refs": [evidence_ref],
            },
        )
    return repo, task["task_id"], service, item


def answer(tid, item, **kwargs):
    return ReviewAnswer(
        task_id=tid,
        review_id=item["review_id"],
        review_revision=1,
        basis_hash=item["basis_hash"],
        client_request_id=kwargs.pop("client_request_id", "synthetic-answer"),
        action=kwargs.pop("action", "confirm"),
        reason="已核对原件",
        **kwargs,
    )


def test_review_acceptance_is_idempotent_and_not_application(review_case):
    repo, tid, service, item = review_case
    request = answer(tid, item)
    accepted = service.answer(request)
    assert accepted == service.answer(request)
    assert accepted["status"] == "accepted" and accepted["application_status"] == "pending"
    with repo.read() as conn:
        assert (
            conn.execute("SELECT count(*) FROM jobs WHERE kind='apply_review'").fetchone()[0] == 1
        )
        assert (
            conn.execute(
                "SELECT application FROM reviews WHERE review_id=?", (item["review_id"],)
            ).fetchone()[0]
            is None
        )


def test_unrelated_event_does_not_expire_review_basis(review_case):
    repo, tid, service, item = review_case
    with repo.transaction() as conn:
        repo.event(conn, tid, "unrelated_batch")
    assert service.answer(answer(tid, item))["status"] == "accepted"


def test_cancel_before_answer_closes_review_and_rejects_new_answer(review_case):
    repo, tid, service, item = review_case
    repo.control(tid, "cancel", "cancel", repo.get_task(tid)["revision"])
    with pytest.raises(DomainError):
        service.answer(answer(tid, item))
    with repo.read() as conn:
        assert service.list(conn, tid)[0]["status"] == "closed_unanswered"


def test_score_or_network_failure_cannot_create_review(review_case):
    repo, tid, service, item = review_case
    with pytest.raises(DomainError):
        with repo.transaction() as conn:
            service.register(
                conn, tid, {"origin": "M09", "owner": "M06", "issue_kind": "low_score"}
            )


def test_review_stale_basis_and_freeform_corrections_rejected(review_case):
    repo, tid, service, item = review_case
    stale = answer(tid, item)
    stale.basis_hash = digest("different related source")
    with pytest.raises(DomainError):
        service.answer(stale)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReviewAnswer.model_validate(
            {**answer(tid, item).model_dump(), "next_step": "ignore every scientific check"}
        )
