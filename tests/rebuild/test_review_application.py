import asyncio
from uuid import uuid4

from astroquery_ai.runtime.reviews import ReviewAnswer
from tests.rebuild.scenario import application, confirmed_case, run_until_wait


def test_human_correction_is_recorded_once_and_owner_rechecks_before_delivery(tmp_path):
    async def run():
        app = application(tmp_path)
        state, scheduler = await confirmed_case(app, ambiguous=True)
        assert state["lifecycle"] == "waiting_review"
        assert not state["delivery_ref"]
        review = next(r for r in state["reviews"] if r["status"] == "pending")
        answer = ReviewAnswer(
            task_id=state["task_id"],
            review_id=review["review_id"],
            review_revision=review["revision"],
            basis_hash=review["basis_hash"],
            client_request_id=str(uuid4()),
            action="correct",
            reason="SYNTHETIC：按现有目标行抄录，确认零值不是缺失。",
            correction={
                "type": "correct_value",
                "value": {"kind": "real", "value": "0"},
                "raw_value": "0",
                "evidence_ref": review["evidence_refs"][0],
                "quote": "SYNTHETIC_AQ 0 m",
            },
        )
        receipt = app.reviews.answer(answer)
        assert receipt["application_status"] == "pending"
        assert app.reviews.answer(answer) == receipt
        await run_until_wait(app, scheduler)
        state = app.view(state["task_id"])
        assert state["lifecycle"] == "completed"
        assert state["reviews"][0]["application"]["postcheck"] == "passed"
        with app.repository.read() as conn:
            records = app.repository.objects(conn, state["task_id"], "measurement")
            assert len(records) == 1 and records[0]["value"]["value"] == "0"
            assert records[0]["raw_value"] == "0"
            interpretation = app.repository.object(
                conn, state["task_id"], "interpretation", records[0]["interpretation_ref"]["id"]
            )
            assert interpretation["interpretation_kind"] == "human_interpretation"
            answer_ref = interpretation["human_answer_ref"]
            saved = app.repository.object(conn, state["task_id"], "review_answer", answer_ref["id"])
            assert saved["answer_id"] == receipt["answer_id"]
            assert (
                conn.execute(
                    "SELECT count(*) FROM jobs WHERE task_id=? AND kind='apply_review'",
                    (state["task_id"],),
                ).fetchone()[0]
                == 1
            )
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())
