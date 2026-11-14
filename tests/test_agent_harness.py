"""Offline follow-up contract checks using a shipped scientific delivery."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.agent_harness import AgentController, AgentStore, DomainTools, GroundingVerifier, load_task_bundle
from astroquery_ai.agent_harness.answer import AnswerProjection, provider_format, stream_specs
from astroquery_ai.agent_harness.controller import selected_view
from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.published_demos import PublishedDemos

SAMPLE_TASK_ID = "e030fefb-3db1-479e-af8b-eb710233e539"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    application = Application(tmp_path_factory.mktemp("agent"))
    application.configuration.runtime = {}
    assert PublishedDemos(application).open(SAMPLE_TASK_ID)
    return application


@pytest.fixture(scope="module")
def bundle(app):
    return load_task_bundle(SAMPLE_TASK_ID, app)


def test_tools_read_frozen_delivery(bundle):
    tools = DomainTools(bundle)
    assert bundle.measurements_by_id and bundle.definitions_by_id and bundle.sources_by_id
    mid = bundle.measurements[0]["measurement_id"]
    assert f"[REC:{mid}]" in tools.execute_tool("get_measurement_provenance", {"measurement_id": mid})
    requests = {
        "query_measurements": ({"property_name": "色散量", "limit": 4}, "[REC:"),
        "get_property_definition": ({"property_name": "色散量"}, "[DEF:"),
        "search_literature": ({"query_terms": "pulsar"}, "[SOURCE:"),
        "get_figure_evidence": ({"property_keyword": "dispersion"}, "[FIG:"),
        "get_scientific_theory": ({"property_name": "色散量"}, "[THEORY:"),
    }
    for name, (args, expected) in requests.items():
        assert expected in tools.execute_tool(name, args)
    assert tools.execute_tool("inspect_differences_and_arbitration", {"property_name": "色散量"})


def test_bound_records_reject_invented_values_and_markers(bundle):
    resolver = GroundingVerifier(bundle)
    projection = AnswerProjection(bundle, resolver)
    record = bundle.measurements[0]
    mid = record["measurement_id"]
    block, citations = projection.block({"type": "chart", "record_ids": [mid, "invented", mid]}, 0)
    assert [row["id"] for row in block["rows"]] == [mid]
    assert block["rows"][0]["original"] == record["raw_value"]
    assert block["rows"][0]["original_unit"] == record["unit"]
    assert {item["type"] for item in citations} >= {"record", "source"}
    clean, refs = resolver.verify_and_clean(f"原报 [REC:{mid}] 与 [REC:invented]")
    assert "[REC:invented]" not in clean
    assert len(refs) == 1 and refs[0]["payload"]["measurement_id"] == mid
    binding = bundle.definitions_list[0]
    definition = resolver.resolve("DEF:" + binding["property_id"])
    assert definition["payload"]["binding"]["definition"]["name_cn"]
    invalid, _ = projection.block({"type": "table", "record_ids": ["invented"]}, 1)
    assert invalid == {"id": "b2", "type": "unavailable", "kind": "table", "title": ""}


def test_stream_shows_partial_prose_and_only_complete_components():
    partial = '{"blocks":[{"type":"text","markdown":"可见内容","title":"","refs":[]'
    blocks, tail = stream_specs(partial)
    assert not blocks and tail["markdown"] == "可见内容"
    partial += '},{"type":"chart","record_ids":["r1"'
    blocks, tail = stream_specs(partial)
    assert len(blocks) == 1 and not tail
    assert provider_format()["json_schema"]["schema"]["properties"]["blocks"]


def test_store_deduplicates_retries_and_recovers_partial(app, bundle):
    store = AgentStore(app.repository)
    store.delete_messages(SAMPLE_TASK_ID)
    task = SAMPLE_TASK_ID
    try:
        reply, user, history, _ = store.start(task, bundle.scope, "一条问题", "req-test", {})
        assert not history
        duplicate, duplicate_user, *_ = store.start(task, bundle.scope, "一条问题", "req-test", {})
        assert duplicate["id"] == reply["id"] and duplicate_user is None
        with pytest.raises(DomainError):
            store.start(task, bundle.scope, "别的问题", "req-test", {})
        with pytest.raises(DomainError):
            store.start(task, bundle.scope, "另开一轮", "req-busy", {})
        store.save(task, reply["id"], content="留下的文字", blocks=[], citations=[], trace=[])
        store.recover()
        assert store.get_message(task, reply["id"])["status"] == "interrupted"
        retried, same_user, previous, _ = store.start(task, bundle.scope, "", "req-retry", {}, reply["id"])
        assert retried["id"] != reply["id"] and same_user["id"] == user["id"] and not previous
        assert store.get_message(task, reply["id"])["content"] == "留下的文字"
    finally:
        store.recover()
        store.delete_messages(task)


def test_http_persists_before_done_and_keeps_scope(app, bundle, monkeypatch):
    store = AgentStore(app.repository)
    mid = bundle.measurements[0]["measurement_id"]
    source = (bundle.measurements[0]["source_ref"])["id"]

    async def generate(self, history, prompt, *, context=None):
        assert all(item["content"] != prompt for item in history)
        for i, spec in enumerate((
            {"type": "text", "markdown": f"已读取 [REC:{mid}]"},
            {"type": "table", "record_ids": [mid], "columns": ["original", "source"]},
            {"type": "formula", "latex": r"\begin{pmatrix}1&2\\3&4\end{pmatrix}"},
        )):
            block, refs = self.projection.block(spec, i)
            yield {"event": "agent_block", "data": {"block": block, "citations": refs}}
        yield {"event": "agent_done", "data": {"model": "qwen3.8-max", "model_calls": [], "fallback": False}}

    monkeypatch.setattr(AgentController, "run_react_stream", generate)
    api = "/api/tasks/" + SAMPLE_TASK_ID + "/agent"
    try:
        with TestClient(create_app(app.root, start_worker=False, application=app)) as client:
            payload = {**bundle.scope, "content": "看原始测量", "request_id": "test-http-1"}
            response = client.post(api + "/chat", json=payload)
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            done = events[-1]
            assert done["status"] == "complete" and done["scope"] == bundle.scope
            assert store.get_message(SAMPLE_TASK_ID, done["id"])["answer"] == done["answer"]
            replay_request = client.post(api + "/chat", json=payload)
            assert replay_request.text.count("event: agent_done") == 1 and "agent_started" not in replay_request.text
            query = {key: bundle.scope[key] for key in ("delivery_id", "delivery_revision")}
            found = client.get(api + "/messages", params=query).json()["messages"]
            assert [row["role"] for row in found] == ["user", "assistant"]
            for citation in done["citations"]:
                path = f"{api}/messages/{done['id']}/citations/{citation['citation_id']}"
                data = client.get(path, params=query).json()
                assert data["citation"]["marker"] in {f"REC:{mid}", f"SOURCE:{source}"}
                assert client.get(path, params={**query, "delivery_revision": 99}).status_code >= 400
    finally:
        store.delete_messages(SAMPLE_TASK_ID)


def test_missing_connection_keeps_scoped_records(bundle):
    async def run():
        ctrl = AgentController(bundle, application=SimpleNamespace(configuration=SimpleNamespace(runtime={})))
        events = [event async for event in ctrl.run_react_stream([], "核查色散量")]
        result = events[-1]["data"]
        assert result["fallback"] and result["model"] is None
        assert result["answer"]["blocks"][1]["rows"]
        assert result["citations"]
    asyncio.run(run())


def test_http_handles_malformed_components_and_empty_model_output(app, bundle, monkeypatch):
    async def generate(self, history, prompt, *, context=None):
        if "有正文" in prompt:
            for i, spec in enumerate((
                {"type": "text", "markdown": "应当保存的正文"},
                {"type": "table", "title": {"bad": "unexpected object"}, "record_ids": []},
            )):
                block, refs = self.projection.block(spec, i)
                yield {"event": "agent_block", "data": {"block": block, "citations": refs}}
        yield {"event": "agent_done", "data": {"model": "qwen3.8-max", "model_calls": [], "fallback": False}}

    monkeypatch.setattr(AgentController, "run_react_stream", generate)
    api = "/api/tasks/" + SAMPLE_TASK_ID + "/agent"
    store = AgentStore(app.repository)
    try:
        with TestClient(create_app(app.root, start_worker=False, application=app)) as client:
            def send(content, request_id, **kwargs):
                res = client.post(api + "/chat", json={**bundle.scope, "content": content,
                                  "request_id": request_id, **kwargs})
                assert res.status_code == 200
                assert res.text.count("event: agent_done") == 1
                return [json.loads(line[6:]) for line in res.text.splitlines()
                        if line.startswith("data: ")][-1]
            partial = send("有正文，但表格结构异常", "bad-block")
            assert partial["status"] == "complete" and partial["content"] == "应当保存的正文"
            assert [b["type"] for b in partial["answer"]["blocks"]] == ["text", "unavailable"]
            empty = send("没有任何输出", "empty-answer")
            assert empty["status"] == "failed" and "重试" in empty["message"]
            retried = send("", "retry-empty", retry_of=empty["id"])
            assert retried["status"] == "failed" and retried["question_id"] == empty["question_id"]
    finally:
        store.delete_messages(SAMPLE_TASK_ID)


def test_explicit_chart_of_selected_records_still_renders_if_model_omits_it(bundle, monkeypatch):
    class StubClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        chat = SimpleNamespace(completions=SimpleNamespace())

    async def plan(**kwargs):
        return SimpleNamespace(model="fixture", id="plan", choices=[
            SimpleNamespace(message=SimpleNamespace(tool_calls=[])),
        ])

    async def answer(self, client, messages, calls):
        yield self.projection.block({"type": "text", "markdown": "解释这批测量的条件。"}, 0)

    StubClient.chat.completions.create = plan
    monkeypatch.setattr(AgentController, "_get_client", lambda self: StubClient())
    monkeypatch.setattr(AgentController, "_generate", answer)
    rows = [{"id": row["measurement_id"]} for row in bundle.measurements[:2]]
    context = {"records": rows}

    async def run():
        ctrl = AgentController(bundle)
        stream = [event async for event in ctrl.run_react_stream(
            [], "把选中的记录画成带原报误差的点图，不填缺失误差。", context=context,
        )]
        chart = stream[-1]["data"]["answer"]["blocks"][-1]
        assert chart["type"] == "chart" and chart["chart_type"] == "interval"
        assert [row["id"] for row in chart["rows"]] == [row["id"] for row in rows]
        assert len([item for item in stream if item["event"] == "agent_block"]) == 2

    asyncio.run(run())
    assert selected_view("用表格重排刚才两条。", context)["type"] == "table"
    assert selected_view("不要画点图，只解释原报。", context) is None
    assert selected_view("解释画成点图时读者容易误解什么。", context) is None
    assert selected_view("把它画成点图。", {}) is None
    last = {"role": "assistant", "answer": {"blocks": [{"type": "table", "rows": rows}]}}
    assert selected_view("画成图，带上误差。", {}, [last])["record_ids"] == [r["id"] for r in rows]
    last["answer"]["blocks"].append({"type": "table", "rows": rows[:1]})
    assert selected_view("画成图，带上误差。", {}, [last]) is None
