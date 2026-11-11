"""Follow-up API. Generation survives a browser disconnect and is explicitly stoppable."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from astroquery_ai.agent_harness import AgentController, AgentStore, GroundingVerifier, load_task_bundle
from astroquery_ai.agent_harness.answer import answer_text, measurement_row
from astroquery_ai.runtime.errors import DomainError

logger = logging.getLogger("web.agent_routes")

TOOL_ACTIVITY = {
    "query_measurements": "查阅本次测量",
    "get_measurement_provenance": "回查原件位置",
    "get_property_definition": "查阅性质定义",
    "search_literature": "查阅来源资料",
    "inspect_differences_and_arbitration": "查阅多源对照",
    "get_figure_evidence": "查阅研究图像",
    "get_scientific_theory": "查阅科学知识",
}


def _reference_labels(citations):
    return [{key: c[key] for key in ("citation_id", "type", "id", "marker", "label")}
            for c in citations if c.get("citation_id")]


def _public(message):
    return {**{key: value for key, value in message.items() if key not in {"operation", "context"}},
            "citations": _reference_labels(message["citations"])}


def _is_current_delivery(task, scope):
    reference = task.get("delivery_ref")
    if isinstance(reference, (str, bytes)):
        reference = json.loads(reference)
    ref = reference or {}
    return (ref.get("id"), ref.get("version")) == (scope["delivery_id"], scope["delivery_revision"])


class Selection(BaseModel):
    message_id: str
    block_id: str
    values: dict[str, float] = Field(default_factory=dict, max_length=6)


class Followup(BaseModel):
    content: str = Field(default="", max_length=12000)
    query: str = Field(default="", max_length=12000)
    request_id: str | None = Field(default=None, max_length=96)
    delivery_id: str | None = None
    delivery_revision: int | None = Field(default=None, ge=1)
    snapshot_ref: dict | None = None
    record_ids: list[str] = Field(default_factory=list, max_length=40)
    markers: list[str] = Field(default_factory=list, max_length=16)
    selections: list[Selection] = Field(default_factory=list, max_length=6)
    selected_answers: list[str] = Field(default_factory=list, max_length=24)
    retry_of: str | None = None
    repair_block: str | None = None


def _conversation(rows, preferences):
    alternatives = {}
    for row in rows:
        if row["role"] == "assistant" and row["question_id"] and row["content"]:
            alternatives.setdefault(row["question_id"], []).append(row)
    history = []
    for row in rows:
        if row["question_id"]:
            continue
        history.append(row)
        options = alternatives.get(row["id"], [])
        if options:
            chosen = next((r for r in options if r["id"] in preferences), options[-1])
            history.append(chosen)
    return history


class Turn:
    def __init__(self, store, message, question, previous, repair_block):
        self.store, self.message = store, message
        self.question = question
        self.previous = previous if repair_block else None
        self.repair_block = repair_block
        self.blocks = {}
        self.citations = {}
        self.trace = []
        self.events = []
        self.changed = asyncio.Event()
        self.closed = False
        self.started = time.monotonic()
        self.task = None
        self.stopping = False

    def emit(self, name, data):
        self.events.append({"event": name, "data": json.dumps(data, ensure_ascii=False)})
        self.changed.set()
        self.changed = asyncio.Event()

    async def stream(self):
        index = 0
        while not self.closed or index < len(self.events):
            changed = self.changed
            while index < len(self.events):
                yield self.events[index]
                index += 1
            if not self.closed:
                await changed.wait()

    def persist(self, status="generating", **meta):
        blocks = list(self.blocks.values())
        return self.store.save(
            self.message["task_id"], self.message["id"], content=answer_text(blocks), blocks=blocks,
            citations=list(self.citations.values()), trace=self.trace, status=status, **meta,
        )

    def repair(self):
        if not self.previous:
            return
        base = self.previous["answer"]["blocks"]
        old_block = next(b for b in base if b["id"] == self.repair_block)
        expected = old_block.get("kind") or old_block["type"]
        replacement = next((block for block in self.blocks.values() if block["type"] == expected), None)
        if replacement:
            replacement = {**replacement, "id": self.repair_block}
        else:
            replacement = old_block
        self.blocks = {b["id"]: replacement if b["id"] == self.repair_block else b for b in base}
        self.citations = {**{c["citation_id"]: c for c in self.previous["citations"]}, **self.citations}

    async def run(self, controller, history, context):
        self.emit("agent_started", {"message": _public(self.message), "question": _public(self.question)})
        prompt = self.question["content"]
        if self.previous:
            block = next(b for b in self.previous["answer"]["blocks"] if b["id"] == self.repair_block)
            kind = block.get("kind") or block["type"]
            prompt += f"\n只重新生成这一个组件：{block['title'] or kind}，组件类型为 {kind}。"
        status = "interrupted"
        meta = {}
        last_saved = 0.0
        try:
            async for event in controller.run_react_stream(history, prompt, context=context):
                name, data = event["event"], event["data"]
                if name == "agent_block":
                    block = data["block"]
                    self.blocks[block["id"]] = block
                    self.citations.update((c["citation_id"], c) for c in data["citations"])
                    if time.monotonic() - last_saved > 0.25:
                        self.persist()
                        last_saved = time.monotonic()
                    data = {**data, "citations": _reference_labels(data["citations"])}
                elif name == "agent_tool_call":
                    self.trace.append({"tool": data["tool"], "step": data["step"], "type": "action"})
                    data = {**data, "label": TOOL_ACTIVITY.get(data["tool"], "查阅交付资料")}
                elif name == "agent_thought":
                    name, data = "agent_status", {"label": data["thought"]}
                elif name == "agent_done":
                    meta = {key: data.get(key) for key in ("model", "model_calls", "fallback")}
                    status = "complete"
                    break
                elif name == "agent_failed":
                    meta = {"message": data["message"]}
                    break
                if name not in {"agent_block", "agent_token"} or not self.previous:
                    self.emit(name, data)
        except asyncio.CancelledError:
            status = "stopped" if self.stopping else "interrupted"
        except Exception:
            logger.exception("Follow-up generation failed for %s", self.message["id"])
            status = "failed"
            meta = {"message": "回答暂时无法生成，可以重试"}
        finally:
            try:
                self.repair()
                if status == "complete" and not any(
                    block["type"] != "unavailable"
                    and (block["type"] != "text" or block["markdown"].strip())
                    for block in self.blocks.values()
                ):
                    status = "failed"
                    meta["message"] = "这次没有生成可读内容，可以重试"
                message = self.persist(status, elapsed_seconds=round(time.monotonic() - self.started, 2), **meta)
                self.emit("agent_done", {**_public(message), "message_id": message["id"]})
            finally:
                self.closed = True
                self.changed.set()


def register(app, application, scheduler):
    store = AgentStore(application.repository)
    active = {}
    app.state.recover_followups = store.recover

    async def close_followups():
        tasks = [turn.task for turn in active.values() if turn.task is not None and not turn.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app.state.close_followups = close_followups

    def task_check(task_id):
        task = application.repository.get_task(task_id)
        if task["kind"] == "replay":
            raise DomainError("REPLAY_READ_ONLY", "退出回放后即可追问")

    def message_context(task_id, body, bundle):
        verifier = GroundingVerifier(bundle)
        references = []
        for marker in body.markers:
            ref = verifier.resolve(marker)
            if ref:
                references.append({"marker": ref["marker"], "label": ref["label"]})
        records = []
        for mid in dict.fromkeys(body.record_ids):
            source = bundle.measurements_by_id.get(mid)
            if source:
                row = measurement_row(bundle, source)
                records.append({k: row[k] for k in ("id", "property", "original", "original_unit", "source", "error")})
        selected = []
        for selection in body.selections:
            try:
                message = store.get_message(task_id, selection.message_id)
            except DomainError:
                continue
            if message["scope"] != bundle.scope:
                continue
            block = next((b for b in (message.get("answer") or {}).get("blocks", [])
                          if b["id"] == selection.block_id and b["type"] == "explore"), None)
            if block:
                parameters = [{"name": p["name"], "unit": p["unit"], "value": selection.values[p["name"]]}
                              for p in block["parameters"] if p["name"] in selection.values
                              and p["min"] <= selection.values[p["name"]] <= p["max"]]
                selected.append({"expression": block["expression"], "parameters": parameters})
        return {key: value for key, value in {"records": records, "references": references, "parameters": selected}.items() if value}

    def legacy_citations(message, bundle):
        text, citations = GroundingVerifier(bundle).verify_and_clean(message["content"])
        return {**message, "content": text, "citations": citations, "legacy": True}

    def display_scope(task_id, delivery_id, revision):
        with application.repository.read() as conn:
            task = application.repository.task(conn, task_id)
            body = application.delivery.read_for_display(conn, task_id, delivery_id, revision)
            scope = {"delivery_id": body["delivery_id"], "delivery_revision": body["revision"],
                     "snapshot_ref": body["snapshot_ref"]}
        return scope, _is_current_delivery(task, scope)

    @app.get("/api/tasks/{task_id}/agent/messages")
    def get_agent_messages(task_id: str, delivery_id: str | None = None, delivery_revision: int | None = None):
        task_check(task_id)
        if delivery_id or delivery_revision is not None:
            scope, latest = display_scope(task_id, delivery_id, delivery_revision)
            rows = store.get_messages(task_id, scope)
            if not latest:
                rows = [row for row in rows if row["scope"]]
            if any(not row["scope"] and row["role"] == "assistant" for row in rows):
                bundle = load_task_bundle(task_id, application, delivery_id, delivery_revision)
                rows = [legacy_citations(row, bundle) if not row["scope"] and row["role"] == "assistant"
                        else row for row in rows]
            return {"scope": scope, "messages": [_public(row) for row in rows]}
        return {"messages": [_public(row) for row in store.get_messages(task_id)]}

    @app.get("/api/tasks/{task_id}/agent/messages/{message_id}/citations/{citation_id}")
    def resolve_citation(task_id: str, message_id: str, citation_id: str,
                         delivery_id: str | None = None, delivery_revision: int | None = None):
        task_check(task_id)
        message = store.get_message(task_id, message_id)
        scope = message["scope"]
        if not scope:
            _, latest = display_scope(task_id, delivery_id, delivery_revision)
            if not latest:
                raise DomainError("DELIVERY_CHANGED", "旧回答仅随当前交付查看")
            bundle = load_task_bundle(task_id, application, delivery_id, delivery_revision)
            message = legacy_citations(message, bundle)
            scope = bundle.scope
        elif (delivery_id and delivery_id != scope["delivery_id"]) or (
                delivery_revision is not None and delivery_revision != scope["delivery_revision"]):
            raise DomainError("DELIVERY_CHANGED", "引用属于另一版交付")
        turn = active.get(message_id)
        citation = turn.citations.get(citation_id) if turn else None
        citation = citation or next((c for c in message["citations"] if c["citation_id"] == citation_id), None)
        if not citation:
            raise DomainError("AGENT_CITATION_NOT_FOUND", "本回答中没有可定位的这条引用", 404)
        return {"scope": scope, "citation": citation}

    @app.delete("/api/tasks/{task_id}/agent/messages")
    def delete_agent_messages(task_id: str):
        task_check(task_id)
        return {"deleted": True, "count": store.delete_messages(task_id)}

    @app.post("/api/tasks/{task_id}/agent/messages/{message_id}/stop")
    async def stop_followup(task_id: str, message_id: str):
        task_check(task_id)
        message = store.get_message(task_id, message_id)
        turn = active.get(message_id)
        if turn and message["status"] == "generating":
            if not turn.stopping:
                turn.stopping = True
                turn.task.cancel()
            try:
                await asyncio.shield(turn.task)
            except asyncio.CancelledError:
                if not turn.task.cancelled():
                    raise
                # A stop can arrive before the generation coroutine first runs.
                stopped = turn.persist("stopped", elapsed_seconds=0)
                turn.emit("agent_done", {**_public(stopped), "message_id": stopped["id"]})
                turn.closed = True
                turn.changed.set()
            message = store.get_message(task_id, message_id)
        return _public(message)

    @app.post("/api/tasks/{task_id}/agent/chat")
    async def agent_chat_stream(task_id: str, body: Followup):
        content = (body.content or body.query).strip()
        if not content and not body.retry_of:
            raise DomainError("AGENT_QUESTION_EMPTY", "请输入要追问的问题", 422)
        bundle = await asyncio.to_thread(load_task_bundle, task_id, application,
                                         body.delivery_id, body.delivery_revision, body.snapshot_ref)
        context = message_context(task_id, body, bundle)
        if body.retry_of:
            previous = store.get_message(task_id, body.retry_of)
            context = context or previous.get("context") or {}
            if body.repair_block and not any(b["id"] == body.repair_block and b["type"] != "text"
                                             for b in (previous.get("answer") or {}).get("blocks", [])):
                raise DomainError("AGENT_BLOCK_NOT_FOUND", "该组件已无法单独重试", 422)
        message, question, history, previous = store.start(
            task_id, bundle.scope, content, body.request_id or uuid.uuid4().hex,
            context, body.retry_of, body.repair_block,
        )
        if not question:
            turn = active.get(message["id"])
            if turn:
                return EventSourceResponse(turn.stream(), ping=10)

            async def saved():
                yield {"event": "agent_done", "data": json.dumps({**_public(message), "message_id": message["id"]}, ensure_ascii=False)}

            return EventSourceResponse(saved())

        if not _is_current_delivery(bundle.raw_task, bundle.scope):
            history = [row for row in history if row["scope"]]
        turn = Turn(store, message, question, previous, body.repair_block)
        controller = AgentController(bundle, application)
        turn.task = asyncio.create_task(turn.run(controller, _conversation(history, body.selected_answers), context))
        active[message["id"]] = turn

        def finished(job):
            active.pop(message["id"], None)
            if not job.cancelled() and job.exception() is not None:
                logger.error("Follow-up persistence failed for %s", message["id"], exc_info=job.exception())

        turn.task.add_done_callback(finished)
        return EventSourceResponse(turn.stream(), ping=10)
