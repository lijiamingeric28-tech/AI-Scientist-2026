import asyncio
import csv
import io
from types import SimpleNamespace

import httpx
import pytest

from astroquery_ai.runtime.budget import Budget
from astroquery_ai.runtime.calls import ModelGateway, ModelProfile
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from tests.rebuild.factories import measurement, derived, ref


def test_csv_formula_like_display_text_is_reversible_and_negative_numbers_stay_numeric():
    from astroquery_ai.runtime.delivery import csv_display

    assert csv_display("-1.25") == ("-1.25", False)
    assert csv_display("+1e-8") == ("+1e-8", False)
    assert csv_display('=HYPERLINK("SYNTHETIC")') == ('\'=HYPERLINK("SYNTHETIC")', True)
    assert csv_display("\t@SYNTHETIC")[1] is True


def gateway(tmp_path, stream):
    repo = Repository(tmp_path / "model.sqlite3")
    task = repo.create_task("SYNTHETIC provider protocol test", kind="validation")
    config = SimpleNamespace(
        runtime={
            "dashscope_api_key": "SYNTHETIC-TEST-NOT-A-KEY",
            "dashscope_base_url": "https://example.test/compatible-mode/v1",
        }
    )
    captured = []

    def handle(request):
        captured.append(loads(request.content))
        return httpx.Response(
            200, content=stream.encode(), headers={"content-type": "text/event-stream"}
        )

    budget = Budget(repo)
    return (
        ModelGateway(config, budget, transport=httpx.MockTransport(handle)),
        budget,
        task,
        captured,
    )


def call(model, task):
    return asyncio.run(
        model.json(
            task_id=task["task_id"],
            owner="M06",
            root_id="synthetic",
            messages=[{"role": "user", "content": "SYNTHETIC JSON test"}],
            profile=ModelProfile(model="qwen3.8-flash", thinking=False),
            smoke=True,
        )
    )


def test_budget_deferral_releases_unsent_gateway_traffic_and_model_slots(tmp_path,monkeypatch):
    from astroquery_ai.runtime.throughput import DispatchDeferred
    model,budget,task,captured=gateway(tmp_path,'')
    def blocked(**kwargs):raise DispatchDeferred('work-model-slots:synthetic',0.5)
    monkeypatch.setattr(budget,'reserve',blocked)
    with pytest.raises(DispatchDeferred):call(model,task)
    assert captured==[] and not model.traffic.entries['qwen3.8-flash']
    assert not model.semaphore.locked() and not model.model_semaphores['qwen3.8-flash'].locked()
    with budget.repository.read() as c:
        assert c.execute('select count(*) from attempts').fetchone()[0]==0


def test_duplicate_json_key_is_diagnosed_and_preserved_without_adopting_data(tmp_path):
    raw = '{"n":1,"n":2}'
    chunks = [{'choices': [{'delta': {'content': raw}, 'finish_reason': 'stop'}]},
        {'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}]
    stream = ''.join('data: ' + canonical(c).decode() + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
    model, budget, task, _ = gateway(tmp_path, stream)
    with pytest.raises(DomainError) as caught:
        call(model, task)
    assert caught.value.code == 'INVALID_MODEL_JSON'
    with budget.repository.read() as conn:
        diagnostics = budget.repository.objects(conn, task['task_id'], 'model_response_diagnostic')
        assert len(diagnostics) == 1 and diagnostics[0]['raw_response'] == raw
        assert diagnostics[0]['adopted_as_scientific_data'] is False
        assert budget.repository.objects(conn, task['task_id'], 'measurement') == []
    assert budget.summary()['actual_micros'] > 0


def test_stream_requires_complete_json_and_accounts_reasoning_usage(tmp_path):
    chunks = [
        {
            "id": "synthetic-provider",
            "choices": [{"delta": {"reasoning_content": "synthetic thinking"}}],
        },
        {"choices": [{"delta": {"content": '{"ok":'}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 17},
            },
        },
    ]
    stream = "".join("data: " + canonical(c).decode() + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    model, budget, task, captured = gateway(tmp_path, stream)
    result, receipt = call(model, task)
    assert result == {"ok": True}
    assert budget.summary()["actual_micros"] == 64
    assert captured[0]["enable_thinking"] is False
    assert receipt["thinking_characters"] > 0
    assert len(captured) == 1  # transport has no hidden retries


def test_json_mode_adds_explicit_instruction_before_cost_bound(tmp_path):
    stream = 'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\ndata: [DONE]\n\n'
    model, budget, task, captured = gateway(tmp_path, stream)
    asyncio.run(model.json(task_id=task['task_id'], owner='M06', root_id='SYNTHETIC explicit format',
        messages=[{'role': 'user', 'content': 'SYNTHETIC compare evidence'}],
        profile=ModelProfile(model='qwen3.8-flash', thinking=False), smoke=True))
    assert captured[0]['messages'][0]['role'] == 'system'
    assert 'JSON object' in captured[0]['messages'][0]['content']


def test_provider_rejection_diagnostics_never_copy_error_body_or_secret(tmp_path):
    model, budget, task, _ = gateway(tmp_path, '')
    model.transport = httpx.MockTransport(lambda request: httpx.Response(400,
        content=b'messages must contain json for response_format; SYNTHETIC-TEST-NOT-A-KEY'))
    with pytest.raises(DomainError):
        call(model, task)
    with budget.repository.read() as conn:
        raw = conn.execute('SELECT receipt FROM attempts').fetchone()[0]
    receipt = loads(raw)
    assert receipt['provider_status'] == 400
    assert receipt['provider_rejection'] == 'json_mode_request_rejected'
    assert b'SYNTHETIC-TEST-NOT-A-KEY' not in bytes(raw)
    assert budget.summary()['unknown_count'] == 1  # No retroactive guessed refund.


@pytest.mark.parametrize('headers_started,expected_unknown', [(False, 0), (True, 1)])
def test_only_traced_native_pre_request_failures_release_reservation(tmp_path, monkeypatch, headers_started, expected_unknown):
    from contextlib import asynccontextmanager
    model, budget, task, _ = gateway(tmp_path, '')
    model.transport = None

    class NativeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            trace = kwargs['extensions']['trace']
            await trace('connection.connect_tcp.started', {'SYNTHETIC secret': 'never retain'})
            if headers_started:
                await trace('http11.send_request_headers.started', {'SYNTHETIC secret': 'never retain'})
            await trace('connection.connect_tcp.failed', {})
            raise httpx.ConnectError('SYNTHETIC transport failure')
            yield  # async contextmanager protocol, never reached

    monkeypatch.setattr(httpx, 'AsyncClient', NativeClient)
    with pytest.raises(httpx.ConnectError):
        call(model, task)
    assert budget.summary()['unknown_count'] == expected_unknown
    if not headers_started:
        assert budget.summary()['committed_micros'] == 0
    with budget.repository.read() as conn:
        raw = bytes(conn.execute('SELECT receipt FROM attempts').fetchone()[0])
    assert b'never retain' not in raw


def test_truncated_response_does_not_commit_fragment_but_known_usage_is_charged(tmp_path):
    chunk = {
        "choices": [{"delta": {"content": '{"ok":'}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }
    model, budget, task, captured = gateway(
        tmp_path, "data: " + canonical(chunk).decode() + "\n\ndata: [DONE]\n\n"
    )
    with pytest.raises(DomainError) as error:
        call(model, task)
    assert error.value.code == "INCOMPLETE_MODEL_RESPONSE"
    assert budget.summary()["actual_micros"] == 35


def test_missing_usage_retains_full_reservation(tmp_path):
    model, budget, task, captured = gateway(
        tmp_path,
        'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
    )
    call(model, task)
    assert budget.summary()["unknown_count"] == 1
    assert budget.summary()["committed_micros"] > 0
    with budget.repository.read() as conn:
        dispatches = budget.repository.objects(conn, task['task_id'], 'model_dispatch')
        assert len(dispatches) == 1 and dispatches[0]['profile']['model'] == 'qwen3.8-flash'
        assert dispatches[0]['purpose'] == 'calibration' and dispatches[0]['scientific_qualification'] is None


def test_unvalidated_production_profile_never_dispatches(tmp_path):
    model, budget, task, captured = gateway(tmp_path, "")
    with pytest.raises(DomainError) as error:
        asyncio.run(
            model.json(
                task_id=task["task_id"],
                owner="M06",
                root_id="new",
                messages=[{"role": "user", "content": "new"}],
                profile=ModelProfile(model="qwen3.8-flash"),
                purpose="production",
                smoke=True,
            )
        )
    assert error.value.code == "PROFILE_NOT_VALIDATED"
    assert captured == [] and budget.summary()["committed_micros"] == 0


def test_all_exports_preserve_full_uncertainty_and_source_objects():
    from tests.rebuild.factories import error_component

    record = measurement(components=[error_component("stat"), error_component("sys", role="sys")])
    body = {
        "delivery_id": "synthetic-delivery",
        "measurements": [record],
        "derived": [derived(record)],
        "contexts": [],
        "snapshot_ref": ref(),
    }
    raw, _ = DeliveryService._serialize(body, "csv_long")
    row = next(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert loads(row["source_measurement_json"]) == record
    assert len(loads(row["uncertainty_source_json"])["components"]) == 2
    raw, _ = DeliveryService._serialize(body, "json_wide")
    assert len(loads(raw)["values"]["synthetic-property"]) == 1


def test_wide_export_retains_all_measurements_and_individual_units():
    first, second = measurement("first"), measurement("second")
    second["unit"] = "cm"
    body = {
        "delivery_id": "synthetic",
        "measurements": [first, second],
        "derived": [],
        "contexts": [],
    }
    raw, _ = DeliveryService._serialize(body, "csv_wide")
    row = next(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    values = loads(row["synthetic-property"])
    assert [v["source"]["unit"] for v in values] == ["m", "cm"]


def test_source_http_no_confirmation_or_no_network_permission_never_dispatches(tmp_path):
    from astroquery_ai.runtime.http import ScientificHTTP

    repo = Repository(tmp_path / "http.sqlite3")
    task = repo.create_task("synthetic")
    captures = []

    def handle(request):
        captures.append(request)
        return httpx.Response(200, json={})

    http = ScientificHTTP(repo, transport=httpx.MockTransport(handle))
    for owner, endpoint in [
        ("M03", "https://example.test/"),
        ("M09", "https://example.test/"),
        ("M01", "https://127.0.0.1/private"),
    ]:
        with pytest.raises(DomainError):
            asyncio.run(http.request(task["task_id"], owner, "synthetic", "GET", endpoint))
    assert captures == []
