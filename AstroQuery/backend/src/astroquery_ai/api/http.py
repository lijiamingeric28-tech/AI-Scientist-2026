"HTTP adapter for the persistent application. No business graph in routes."

from __future__ import annotations

import asyncio
import logging

from .routes import settings, tasks, events, results, retired, agent, knowledge

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request

from fastapi.responses import JSONResponse

from fastapi.staticfiles import StaticFiles

from astroquery_ai.runtime.application import Application

from astroquery_ai.runtime.codec import loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.lifecycle import InstanceLock

from astroquery_ai.runtime.scheduler import Scheduler

from astroquery_ai.runtime.paths import data_root, frontend_dist


def create_app(
    root: Path | None = None, *, start_worker=True, allow_synthetic=False, application=None
) -> FastAPI:
    root = data_root(root)
    lock = InstanceLock(root)
    with lock:
        application = application or Application(root, allow_synthetic=allow_synthetic)
    scheduler = Scheduler(
        application,
        task_id=application.pilot.task_id if getattr(application, "pilot", None) else None,
    )

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        closing = asyncio.Event()
        async def prepare_worker():
            try:
                await asyncio.to_thread(application.registry.load)
                app.state.scientific_startup = 'ready'
            except DomainError:
                # Jobs retain their existing registry error handling.
                app.state.scientific_startup = 'library_unavailable'
            except Exception:
                app.state.scientific_startup = 'failed'
                logging.getLogger(__name__).exception("Scientific worker preflight failed")
                return
            if start_worker and not closing.is_set():
                await scheduler.start()

        warmup = None
        try:
            application.repository.recover()
            app.state.recover_followups()
            app.state.scientific_startup = 'preparing'
            # The historical reader can open immediately after recovery. New work
            # still waits for the same registry preflight before taking any lease.
            warmup = asyncio.create_task(prepare_worker())
            yield
        finally:
            closing.set()
            try:
                await app.state.close_followups()
                if warmup:
                    await warmup
            finally:
                try:
                    if start_worker:
                        await scheduler.stop()
                finally:
                    lock.release()

    app = FastAPI(title="AstroQuery AI", version="3.0.0-dev", lifespan=lifespan)
    app.state.application, app.state.scheduler = (application, scheduler)
    from astroquery_ai.runtime.published_demos import PublishedDemos
    published = PublishedDemos(application)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"detail": error.as_dict()}, status_code=error.status)

    @app.middleware("http")
    async def local_write_guard(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if "application/json" in request.headers.get("content-type", ""):
                try:
                    body = await request.body()
                    if len(body) > 2 * 1024**2:
                        raise ValueError("body limit")
                    document = loads(body)
                    if not isinstance(document, dict):
                        raise ValueError("JSON object required")
                    if "expected_revision" in document and (
                        type(document["expected_revision"]) is not int
                        or document["expected_revision"] < 1
                    ):
                        raise ValueError("positive integer revision required")
                except (ValueError, UnicodeError):
                    return JSONResponse(
                        {
                            "detail": {
                                "code": "INVALID_JSON",
                                "message": "JSON含重复键、非法数值、格式错误或超过大小限制",
                            }
                        },
                        status_code=422,
                    )
            origin = request.headers.get("origin")
            from urllib.parse import urlsplit

            if origin:
                origin_parts = urlsplit(origin)
                req_parts = urlsplit(str(request.url))
                is_local = (
                    origin_parts.hostname in {"127.0.0.1", "localhost", "::1"}
                    and req_parts.hostname in {"127.0.0.1", "localhost", "::1"}
                )
                if origin_parts.netloc != request.url.netloc and not is_local:
                    return JSONResponse(
                        {
                            "detail": {
                                "code": "CROSS_ORIGIN_WRITE",
                                "message": "不允许跨来源修改本地科研任务",
                            }
                        },
                        status_code=403,
                    )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {
                        "detail": {
                            "code": "CROSS_ORIGIN_WRITE",
                            "message": "不允许跨来源修改本地科研任务",
                        }
                    },
                    status_code=403,
                )
        try:
            await published.prepare_request(request)
        except DomainError as error:
            return JSONResponse({"detail": error.as_dict()}, status_code=error.status)
        return await call_next(request)

    settings.register(app, application, scheduler)
    control = tasks.register(app, application, scheduler)
    events.register(app, application, scheduler)
    results.register(app, application, scheduler)
    retired.register(app, application, scheduler)
    agent.register(app, application, scheduler)
    knowledge.register(app, application, scheduler)
    app.add_api_route("/api/tasks/{task_id}/{action}", control, methods=["POST"])
    frontend = frontend_dist()
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
