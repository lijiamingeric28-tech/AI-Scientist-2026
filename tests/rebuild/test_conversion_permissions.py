import asyncio
from copy import deepcopy

from astroquery_ai.registry.models import Representation
from astroquery_ai.science.conversion_policy import conversion_permission
from tests.rebuild.scenario import application, confirmed_case


def test_unpublished_numeric_policy_blocks_even_identical_unit_and_representation():
    source = {"value": {"kind": "real", "value": "1"}, "unit": "m", "representation": "linear"}
    target = {"unit": {"canonical_symbol": "m"}, "representation": {"kind": "linear"}}
    permission = conversion_permission(
        {"numeric_paths_state": "not_published", "allowed_transforms": ["identity"]},
        source,
        target,
        Representation(kind="linear"),
    )
    assert permission == {"allowed": False, "reason": "numeric_execution_not_published"}
    assert not conversion_permission(
        {"allowed_transforms": []}, source, target, Representation(kind="linear")
    )["allowed"]
    assert conversion_permission(
        {"allowed_transforms": ["identity"]}, source, target, Representation(kind="linear")
    )["allowed"]


def test_unpublished_policy_actual_job_keeps_source_and_exports_without_conversion_model(tmp_path):
    async def run():
        app = application(tmp_path)
        release = app.registry.load()
        restricted = deepcopy(release)
        policy = restricted["data"]["conversion-policies"][0]
        policy["numeric_paths_state"] = "not_published"
        # This test changes only the policy consumed by the service, not frozen
        # registry approval or external inputs. It asserts dispatch behavior.
        original_load = app.registry.load

        def load(release_id=None):
            actual = original_load(release_id)
            actual["data"]["conversion-policies"][0]["numeric_paths_state"] = "not_published"
            return actual

        app.registry.load = load
        state, _ = await confirmed_case(app)
        assert state["lifecycle"] == "completed"
        with app.repository.read() as conn:
            body = app.delivery.get(conn, state["task_id"])
            assert len(body["measurements"]) == 1 and body["measurements"][0]["raw_value"] == "0"
            assert body["derived"][0]["status"] == "not_run"
            assert body["derived"][0]["issues"] == [{"code": "numeric_execution_not_published"}]
            assert (
                app.repository.objects(conn, state["task_id"], "quality")[0]["measurements"][0][
                    "delivery"
                ]
                is None
            )
        assert app.budget.summary()["committed_micros"] == 0

    asyncio.run(run())
