"""Fresh synthetic counterexamples for owner recheck, not scientific validation."""

import asyncio
from uuid import uuid4

import httpx

from astroquery_ai.runtime.reviews import ReviewAnswer
from tests.rebuild.scenario import application, confirmed_case, run_until_wait, ScenarioModels
from tests.rebuild.test_new_end_to_end import XML_HEADER


def answer_for(state, review, action, correction=None):
    return ReviewAnswer(
        task_id=state["task_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        basis_hash=review["basis_hash"],
        client_request_id=str(uuid4()),
        action=action,
        reason="SYNTHETIC：按当前保存的原件核对。",
        correction=correction,
    )


def test_invalid_human_value_is_retained_for_editing_and_three_failures_pause(tmp_path):
    async def run():
        app = application(tmp_path)
        state, scheduler = await confirmed_case(app, ambiguous=True)
        for index in range(3):
            review = state["reviews"][0]
            correction = {
                "type": "correct_value",
                "value": {"kind": "real", "value": "999"},
                "raw_value": "999",
                "evidence_ref": review["evidence_refs"][0],
                "quote": "SYNTHETIC source says 0; this deliberately wrong edit must fail.",
            }
            app.reviews.answer(answer_for(state, review, "correct", correction))
            await run_until_wait(app, scheduler)
            state = app.view(state["task_id"])
            assert len(state["reviews"]) == 1 and state["reviews"][0]["revision"] == index + 2
            assert state["reviews"][0]["status"] == "pending"
            assert state["reviews"][0]["rejected_answer"]["correction"]["raw_value"] == "999"
            with app.repository.read() as conn:
                assert app.repository.objects(conn, state["task_id"], "measurement") == []
        assert state["lifecycle"] == "paused"
        app.repository.control(state["task_id"], "continue", str(uuid4()), state["revision"])
        state = app.view(state["task_id"])
        review = state["reviews"][0]
        correction.update(
            value={"kind": "real", "value": "0"},
            raw_value="0",
            quote="SYNTHETIC original target cell is 0.",
        )
        app.reviews.answer(answer_for(state, review, "correct", correction))
        await run_until_wait(app, scheduler)
        state = app.view(state["task_id"])
        assert state["lifecycle"] == "completed" and state["reviews"][0]["status"] == "resolved"
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())


def test_optional_unresolved_error_review_unable_keeps_main_value(tmp_path):
    async def run():
        app = application(tmp_path)

        class Models(ScenarioModels):
            async def json(self, *, owner, **kwargs):
                response, receipt = await super().json(owner=owner, **kwargs)
                if owner == "M03":
                    if "id_column" in response:
                        response["properties"][0]["error_columns"] = ["e_Length"]
                    elif response.get("results"):
                        response["results"][0]["errors"] = [
                            {
                                "location": "e_Length",
                                "raw_text": "0.2",
                                "kind": "symmetric_delta",
                                "values": None,
                                "role": "unspecified",
                                "meaning": "reported_error",
                                "interpretation_state": "unresolved",
                                "reason": "SYNTHETIC unclear source meaning",
                            }
                        ]
                return response, receipt

        app.models = Models()

        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404, text='SYNTHETIC: no ReadMe')
            if request.url.host == "api.adsabs.harvard.edu":
                return httpx.Response(200, json={"response": {"numFound": 0, "docs": []}})
            if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
                header = (
                    XML_HEADER
                    + b'<FIELD name="e_Length" datatype="double" unit="m"><DESCRIPTION>Source reported error</DESCRIPTION></FIELD>'
                )
                data = (
                    b"<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0</TD><TD>0.2</TD></TR></TABLEDATA></DATA>"
                    if "Name" in request.url.params
                    else b""
                )
                return httpx.Response(200, content=header + data + b"</TABLE></RESOURCE></VOTABLE>")
            raise AssertionError("No external network")

        app.http.transport = httpx.MockTransport(handle)
        state, scheduler = await confirmed_case(app)
        assert state['reviews'] == []
        assert state["lifecycle"] == "completed"
        with app.repository.read() as conn:
            body = app.delivery.get(conn, state["task_id"])
            assert len(body["measurements"]) == 1 and body["measurements"][0]["raw_value"] == "0"
            assert body["measurements"][0]["uncertainty"]["components"][0]["raw_text"] == "0.2"
            report = app.repository.object(
                conn, state["task_id"], "quality", body["quality"]["report_ref"]["id"]
            )
            assert any(
                issue["rule_id"] == "reported_uncertainty_unresolved"
                and issue["impact"]["dimension"] == "none"
                for issue in report["issues"]
            )
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())
