"""Existing events HTTP routes; business services retain authority."""

from __future__ import annotations

import asyncio

from fastapi import Request

from fastapi.responses import StreamingResponse

from astroquery_ai.runtime.codec import canonical

from astroquery_ai.runtime.models import TERMINAL


def register(app, application, scheduler):

    @app.get("/api/tasks/{task_id}/events")
    @app.get("/api/tasks/{task_id}/events/history")
    def events(task_id: str, after_seq: int = 0, limit: int = 200):
        return {"items": application.repository.events(task_id, after_seq, limit)}

    @app.get("/api/tasks/{task_id}/events/stream")
    async def stream(task_id: str, request: Request, after_seq: int = 0):
        application.repository.events(task_id, after_seq, 1)

        async def generate():
            cursor = after_seq
            first = True
            while not await request.is_disconnected():
                view = application.view(task_id)
                if first:
                    yield (
                        "event: handshake\ndata: "
                        + canonical(
                            {
                                "task_revision": view["revision"],
                                "watermark": view["core_event_cursor"],
                            }
                        ).decode()
                        + "\n\n"
                    )
                    first = False
                page = application.repository.events(task_id, cursor, 200)
                for event in page:
                    yield (
                        "id: " + str(event["seq"]) + "\ndata: " + canonical(event).decode() + "\n\n"
                    )
                    cursor = event["seq"]
                if view["lifecycle"] in TERMINAL and cursor >= view["core_event_cursor"]:
                    yield "event: eof\ndata: {}\n\n"
                    return
                if not page:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
