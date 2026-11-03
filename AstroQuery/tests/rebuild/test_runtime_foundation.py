"""New synthetic acceptance cases. No old samples and no network."""

import concurrent.futures
import sqlite3

import pytest
from pydantic import ValidationError

from astroquery_ai.runtime.budget import Budget, price_for
from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.lifecycle import InstanceLock
from astroquery_ai.runtime.models import UncertaintyBundle, ScalarValue, BooleanValue
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore


@pytest.fixture
def repo(tmp_path):
    return Repository(tmp_path / "runtime.sqlite3")


def live(repo):
    return repo.create_task("synthetic calibration object")


def ref(name="synthetic-ref"):
    return {"id": name, "version": 1, "content_sha256": digest({"synthetic": name})}


def reserve(budget, task, root="synthetic-root", **kwargs):
    return budget.reserve(
        task_id=task["task_id"],
        owner="M06",
        model="qwen3.7-plus",
        root_id=root,
        request={"synthetic": True},
        input_bound=1000,
        output_bound=100,
        smoke=True,
        **kwargs,
    )


def test_canonical_json_rejects_duplicate_and_nonfinite():
    for raw in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'):
        with pytest.raises(ValueError):
            loads(raw)
    assert canonical({"b": 0, "a": False}) == b'{"a":false,"b":0}'


def test_user_uncapped_authorization_preserves_campaign_and_unknown_spend(repo):
    budget = Budget(repo, cap_micros=1)
    task = live(repo)
    with repo.transaction() as conn:
        conn.execute("INSERT INTO settings(key,revision,payload) VALUES(?,?,?)",
            ('campaign_amount_authorization', 1, canonical({
                'schema_version': 'CampaignAmountAuthorization/1',
                'campaign_id': budget.campaign_id, 'mode': 'uncapped', 'authorized_by': 'user'})))
        conn.execute("UPDATE campaigns SET smoke_passed=1")
    first = budget.reserve(
        task_id=task['task_id'], owner='M01', model='qwen3.8-flash', root_id='synthetic',
        request={'synthetic': True}, input_bound=1000, output_bound=100, purpose='calibration')
    budget.dispatch(first['attempt_id'])
    budget.settle(first['attempt_id'], input_tokens=None, output_tokens=None, receipt={})
    summary = budget.summary()
    assert summary['cap_micros'] == 1
    assert summary['effective_cap_micros'] is summary['remaining_micros'] is None
    assert summary['unknown_count'] == 1 and summary['committed_micros'] > 1


def test_future_database_version_is_read_only(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(DomainError, match="高于"):
        Repository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 999


def test_mutation_and_events_rollback_together(repo):
    task = live(repo)
    with pytest.raises(RuntimeError):
        with repo.transaction() as conn:
            repo.mutate_task(conn, task["task_id"], lifecycle="queued")
            repo.event(conn, task["task_id"], "synthetic_rolled_back")
            raise RuntimeError("fault injection")
    assert repo.get_task(task["task_id"])["revision"] == 1
    assert len(repo.events(task["task_id"])) == 1


def test_concurrent_event_sequences_are_contiguous(repo):
    task = live(repo)

    def publish(i):
        with repo.transaction() as conn:
            repo.event(conn, task["task_id"], "synthetic", {"number": i})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(publish, range(32)))
    events = repo.events(task["task_id"])
    assert [e["seq"] for e in events] == list(range(1, 34))
    assert len({e["event_id"] for e in events}) == 33
    with pytest.raises(DomainError) as error:
        repo.events(task["task_id"], after_seq=100)
    assert error.value.code == "RESYNC_REQUIRED"


def test_operation_retransmission_and_conflict(repo):
    task = live(repo)
    answer = repo.control(task["task_id"], "pause", "op-1", 1)
    assert answer == repo.control(task["task_id"], "pause", "op-1", 1)
    with pytest.raises(DomainError) as error:
        repo.control(task["task_id"], "cancel", "op-1", 1)
    assert error.value.code == "OPERATION_CONFLICT"
    assert repo.get_task(task["task_id"])["lifecycle"] == "paused"


def test_old_revision_cannot_cancel_new_state(repo):
    task = live(repo)
    repo.control(task["task_id"], "pause", "op-1", 1)
    with pytest.raises(DomainError) as error:
        repo.control(task["task_id"], "cancel", "op-2", 1)
    assert error.value.code == "REVISION_CONFLICT"


def test_cancel_invalidates_job_lease_and_no_resume(repo):
    task = live(repo)
    with repo.transaction() as conn:
        repo.enqueue(conn, task["task_id"], "M06", "synthetic", {"source": "new-case"})
    job = repo.claim_job("test-worker")
    current = repo.get_task(task["task_id"])
    result = repo.control(task["task_id"], "cancel", "cancel-1", current["revision"])
    assert result["lifecycle"] == "cancelled"
    with pytest.raises(DomainError):
        with repo.transaction() as conn:
            repo.finish_job(conn, job)
    with pytest.raises(DomainError) as error:
        repo.control(task["task_id"], "continue", "resume-1", result["revision"])
    assert error.value.code == "TERMINAL_TASK"


def test_recovery_is_explicit_and_does_not_repeat_completed_jobs(repo):
    task = live(repo)
    with repo.transaction() as conn:
        repo.enqueue(conn, task["task_id"], "M06", "synthetic", {"batch": 1})
        repo.enqueue(conn, task["task_id"], "M06", "synthetic", {"batch": 2})
    job = repo.claim_job("old-worker")
    with repo.transaction() as conn:
        repo.finish_job(conn, job)
    second = repo.claim_job("old-worker")
    assert repo.recover() == 1
    assert repo.claim_job("new-worker") is None
    current = repo.get_task(task["task_id"])
    # Synthetic preparation has no frozen query, so continue returns to waiting_input.
    resumed = repo.control(task["task_id"], "continue", "resume", current["revision"])
    assert resumed["lifecycle"] == "waiting_input"
    with repo.read() as conn:
        assert (
            conn.execute("SELECT status FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0]
            == "succeeded"
        )
        assert (
            conn.execute("SELECT status FROM jobs WHERE job_id=?", (second["job_id"],)).fetchone()[
                0
            ]
            == "ready"
        )


def test_budget_reservation_survives_restart(repo):
    budget = Budget(repo)
    task = live(repo)
    attempt = reserve(budget, task)
    budget.dispatch(attempt["attempt_id"])
    before = budget.summary()["committed_micros"]
    repo.recover()
    again = Budget(Repository(repo.path))
    assert again.summary()["committed_micros"] == before
    assert again.summary()["unknown_count"] == 1
    assert again.summary()["actual_micros"] == 0


def test_unknown_usage_is_not_refunded(repo):
    budget = Budget(repo)
    attempt = reserve(budget, live(repo))
    budget.dispatch(attempt["attempt_id"])
    budget.settle(
        attempt["attempt_id"], input_tokens=None, output_tokens=None, receipt={"timeout": True}
    )
    assert budget.summary()["committed_micros"] == attempt["reserved_micros"]
    assert budget.summary()["unknown_count"] == 1


def test_concurrent_currency_reservation_cannot_overspend(repo):
    budget = Budget(repo, cap_micros=4000)
    tasks = [live(repo) for _ in range(16)]

    def call(task):
        try:
            reserve(budget, task)
            return True
        except DomainError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, tasks))
    assert sum(results) == 1  # reserve=1000*2+100*8=2800 micro-yuan
    assert budget.summary()["committed_micros"] == 2800


def test_campaign_identifier_cannot_reset_cap(repo):
    Budget(repo)
    with pytest.raises(DomainError, match="重置"):
        Budget(repo, campaign_id="another-validation")


def test_cancel_between_reservation_and_dispatch_is_zero_cost(repo):
    budget = Budget(repo)
    task = live(repo)
    attempt = reserve(budget, task)
    repo.control(task["task_id"], "cancel", "cancel", repo.get_task(task["task_id"])["revision"])
    with pytest.raises(DomainError):
        budget.dispatch(attempt["attempt_id"])
    assert budget.summary()["committed_micros"] == 0


def test_late_usage_settlement_is_allowed_after_cancel(repo):
    budget = Budget(repo)
    task = live(repo)
    attempt = reserve(budget, task)
    budget.dispatch(attempt["attempt_id"])
    repo.control(task["task_id"], "cancel", "cancel", repo.get_task(task["task_id"])["revision"])
    budget.settle(
        attempt["attempt_id"],
        input_tokens=200,
        output_tokens=50,
        receipt={"provider_id": "synthetic"},
    )
    assert budget.summary()["actual_micros"] == 800
    with pytest.raises(DomainError):
        reserve(budget, repo.get_task(task["task_id"]), root="another")


def test_long_context_price_is_reserved_before_dispatch():
    assert price_for("qwen3.7-plus", 256000).cost(1000, 100) == 2800
    assert price_for("qwen3.7-plus", 256001).cost(1000, 100) == 8400
    assert price_for("qwen3.8-flash", 1).cost(1, 1) == 4


def test_actual_overrun_records_cost_and_stops_provider(repo):
    budget = Budget(repo)
    task = live(repo)
    attempt = reserve(budget, task)
    budget.dispatch(attempt["attempt_id"])
    with pytest.raises(DomainError) as error:
        budget.settle(attempt["attempt_id"], input_tokens=2000, output_tokens=100, receipt={})
    assert error.value.code == "RESERVATION_VIOLATION"
    assert budget.summary()["actual_micros"] == 4800
    with pytest.raises(DomainError) as error:
        reserve(budget, task, root="new")
    assert error.value.code == "PROVIDER_DISABLED"


def test_immutable_object_and_hash_validation(repo):
    task = live(repo)
    body = {"value": "0", "flag": False, "components": []}
    body["content_sha256"] = content_hash(body)
    with repo.transaction() as conn:
        first = repo.put_object(conn, task["task_id"], "synthetic", "zero", 1, body)
        assert first == repo.put_object(conn, task["task_id"], "synthetic", "zero", 1, body)
    with pytest.raises(DomainError):
        with repo.transaction() as conn:
            repo.put_object(conn, task["task_id"], "synthetic", "zero", 1, {"value": "1"})


def test_artifact_ownership_and_integrity(repo, tmp_path):
    task, other = live(repo), live(repo)
    store = ArtifactStore(tmp_path / "artifacts", repo)
    artifact = store.write(b"new synthetic raw evidence", "text/plain")
    with repo.transaction() as conn:
        store.register(conn, task["task_id"], "synthetic-owner", artifact)
    _, path = store.read_owned(task["task_id"], artifact["artifact_id"])
    with pytest.raises(DomainError):
        store.read_owned(other["task_id"], artifact["artifact_id"])
    with pytest.raises(DomainError):
        store.path("../outside")
    path.write_bytes(b"tampered")
    with pytest.raises(DomainError) as error:
        store.read_owned(task["task_id"], artifact["artifact_id"])
    assert error.value.code == "ARTIFACT_CORRUPT"


def test_single_instance_lock(tmp_path):
    with InstanceLock(tmp_path):
        with pytest.raises(DomainError):
            InstanceLock(tmp_path).acquire()
    with InstanceLock(tmp_path):
        pass


def test_strict_scientific_zero_and_false():
    assert ScalarValue(kind="real", value="0").value == "0"
    assert BooleanValue(kind="boolean", value=False).value is False
    for value in (0, False, "NaN", "Inf"):
        with pytest.raises(ValidationError):
            ScalarValue(kind="real", value=value)


def test_uncertainty_independent_sides_roles_and_levels_round_trip():
    def component(cid, values, role):
        return {
            "component_id": cid,
            "interpretation_state": "parsed",
            "kind": "asymmetric_delta",
            "values": values,
            "role": role,
            "statistical_meaning": "reported_error",
            "level": None,
            "representation_ref": ref(),
            "unit_ref": ref(),
            "basis_ref": None,
            "evidence_refs": [ref()],
            "raw_text": "source asymmetric error",
            "interpretation_provenance": ref(),
        }

    bundle = UncertaintyBundle.model_validate(
        {
            "state": "reported",
            "components": [
                component("stat-1", {"minus": "0.2", "plus": "0.4"}, "stat"),
                component("sys-1", {"minus": None, "plus": "0.1"}, "sys"),
            ],
            "raw_refs": [ref()],
            "reason": None,
            "inspection_ref": ref(),
        }
    )
    restored = UncertaintyBundle.model_validate(loads(canonical(bundle)))
    assert restored == bundle
    assert restored.components[1].values.minus is None
    assert restored.components[0].level is None
    assert [c.role for c in restored.components] == ["stat", "sys"]


def test_unresolved_error_cannot_be_silently_converted_to_no_error():
    with pytest.raises(ValidationError):
        UncertaintyBundle(
            state="not_reported", components=[], raw_refs=[], reason=None, inspection_ref=None
        )
    with pytest.raises(ValidationError):
        UncertaintyBundle(
            state="reported", components=[], raw_refs=[], reason=None, inspection_ref=ref()
        )
