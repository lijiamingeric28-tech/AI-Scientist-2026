"""SYNTHETIC revocation timing with mock provider; no real credential/network."""

import asyncio

import pytest

from astroquery_ai.runtime.calls import ModelProfile
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_provider_and_delivery import gateway


def changing_gateway(tmp_path, change_at):
    chunk = {
        "choices": [{"delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    model, budget, _, captured = gateway(
        tmp_path, "data: " + canonical(chunk).decode() + "\n\ndata: [DONE]\n\n"
    )
    task = budget.repository.create_task("SYNTHETIC profile revocation timing")
    count = 0

    def authorizer(*args):
        nonlocal count
        count += 1
        return {
            "scope_hash": "synthetic-after" if count >= change_at else "synthetic-before",
            "synthetic": False,
        }

    model.profile_authorizer = authorizer

    def call():
        return asyncio.run(
            model.json(
                task_id=task["task_id"],
                owner="M01",
                root_id="synthetic",
                messages=[{"role": "user", "content": "SYNTHETIC"}],
                profile=ModelProfile(model="qwen3.8-flash", state="validated", thinking=False),
                purpose="production",
                smoke=True,
            )
        )

    return call, budget, captured


def test_qualification_changes_before_dispatch_release_reservation_without_provider_call(tmp_path):
    call, budget, captured = changing_gateway(tmp_path, 2)
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.code == "PROFILE_QUALIFICATION_CHANGED"
    assert captured == [] and budget.summary()["committed_micros"] == 0
    with budget.repository.read() as conn:
        assert conn.execute("SELECT status FROM attempts").fetchone()[0] == "not_dispatched"


def test_qualification_changes_during_response_charge_known_usage_and_do_not_release_result(
    tmp_path,
):
    call, budget, captured = changing_gateway(tmp_path, 3)
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.code == "PROFILE_QUALIFICATION_CHANGED"
    assert (
        len(captured) == 1
        and budget.summary()["actual_micros"] > 0
        and budget.summary()["unknown_count"] == 0
    )
    with budget.repository.read() as conn:
        receipt = loads(conn.execute("SELECT receipt FROM attempts").fetchone()[0])
        assert receipt["error_code"] == "PROFILE_QUALIFICATION_CHANGED"
