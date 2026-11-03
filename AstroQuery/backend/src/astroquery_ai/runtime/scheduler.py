"Recoverable worker with durable leases and bounded shutdown."

from __future__ import annotations

import asyncio

import contextlib

from astroquery_ai.runtime.codec import new_id

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.main_graph import create_main_graph

from astroquery_ai.runtime.models import TERMINAL


class Scheduler:
    def __init__(self, application, *, task_id=None):
        self.application = application
        self.repository = application.repository
        self.task_id = task_id
        self.owner_id = new_id()
        self.wake = asyncio.Event()
        self.stopping = False
        self.worker = None
        self.handlers = {"prepare": application.prepare, "reconcile": self.reconcile}
        from astroquery_ai.science.pipeline import SciencePipeline

        self.pipeline = SciencePipeline(application)
        self.handlers.update(self.pipeline.handlers)
        self.graph = create_main_graph(self.dispatch)

    def register(self, kind, handler):
        if kind in self.handlers:
            raise ValueError("duplicate job handler")
        self.handlers[kind] = handler

    async def dispatch(self, job):
        handler = self.handlers.get(job["kind"])
        if handler is None:
            raise DomainError("UNKNOWN_JOB_KIND", "仓储中的作业类型不受当前执行器支持")
        from .run_policy import current_job, ensure_window, guard
        with self.repository.transaction() as conn:
            ensure_window(self.repository, conn, job)
            guard(self.repository, conn, job, dispatch=True)
        token = current_job.set(job)
        try:
            await handler(job)
            await self.pipeline.advance(job["task_id"])
            self.wake.set()
        finally:
            current_job.reset(token)

    async def execute(self, job):
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            return await self.graph.ainvoke({"job": job})

    async def reconcile(self, job):
        with self.repository.transaction() as conn:
            self.repository.finish_job(conn, job)

    async def start(self):
        if self.worker is not None:
            raise RuntimeError("scheduler already started")
        self.worker = asyncio.create_task(self.run_workers())

    async def run_workers(self):
        from astroquery_ai.runtime.stages import EXECUTION_POLICY

        async with asyncio.TaskGroup() as group:
            for _ in range(EXECUTION_POLICY["workers"]):
                group.create_task(self.run())

    async def run(self):
        while not self.stopping:
            self.wake.clear()
            from .run_policy import sweep_ready
            with self.repository.transaction() as conn:
                expired_tasks = sweep_ready(self.repository, conn, task_id=self.task_id)
            for tid in expired_tasks:
                await self.advance_after_expiry(tid)
            job = self.repository.claim_job(self.owner_id, task_id=self.task_id)
            if job is None:
                try:
                    await asyncio.wait_for(
                        self.wake.wait(), timeout=self.repository.dispatch_delay()
                    )
                except TimeoutError:
                    pass
                continue
            await self.run_job(job)

    async def run_job(self, job):
        from .run_policy import ensure_window, remaining
        operation = None
        try:
            with self.repository.transaction() as conn:
                ensure_window(self.repository, conn, job)
            operation = asyncio.create_task(self.execute(job))
            while not operation.done():
                try:
                    with self.repository.read() as conn:
                        left = remaining(self.repository, conn, job)
                    if left is not None and left <= 0:
                        operation.cancel()
                        with contextlib.suppress(asyncio.CancelledError, DomainError):
                            await operation
                        raise DomainError('CATALOG_WINDOW_EXPIRED', '本次星表十分钟窗口已结束')
                    await asyncio.wait_for(asyncio.shield(operation), timeout=min(10, max(.02, left)) if left is not None else 10)
                except TimeoutError:
                    task = self.repository.get_task(job["task_id"])
                    if task["lifecycle"] in TERMINAL | {"cancelling"} or self.stopping:
                        operation.cancel()
                        with contextlib.suppress(asyncio.CancelledError, DomainError):
                            await operation
                        break
                    self.repository.renew(job)
            if not operation.cancelled():
                operation.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                self.fail(job, exc)
            except Exception as followup:
                self.interrupt_task(job["task_id"], followup, job=job,
                                    operation="failure_handling", cause=exc)
            else:
                try:
                    await self.pipeline.advance(job["task_id"])
                except Exception as followup:
                    self.interrupt_task(job["task_id"], followup, job=job,
                                        operation="failure_advance", cause=exc)
        finally:
            # A failed heartbeat/lease check must not leave the provider or
            # parser running after this worker has moved on to another job.
            if operation is not None:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    def interrupt_task(self, task_id, error, *, job=None, operation, cause=None):
        if isinstance(error, DomainError) and error.code in {"TASK_DELETED", "TASK_NOT_FOUND"}:
            return
        repo = self.repository
        with repo.transaction() as conn:
            try:
                task = repo.task(conn, task_id)
            except DomainError as exc:
                if exc.code in {"TASK_DELETED", "TASK_NOT_FOUND"}:
                    return
                raise
            if task['lifecycle'] in TERMINAL or job and task['generation'] != job['generation']:
                return
            if job:
                conn.execute("UPDATE jobs SET status='ready',lease_token=NULL,lease_until=NULL "
                             "WHERE job_id=? AND status='running' AND lease_token=?",
                             (job['job_id'], job['lease_token']))
            if task['query_ref']:
                repo.enqueue(conn, task_id, 'M13', 'reconcile',
                             {'operation': operation, 'after_job_id': job['job_id'] if job else None,
                              'reason': getattr(error, 'code', type(error).__name__)})
            repo.mutate_task(conn, task_id, lifecycle='interrupted', resume_required=1)
            repo.event(conn, task_id, 'orchestration_interrupted',
                       {'operation': operation, 'job_id': job['job_id'] if job else None,
                        'reason': getattr(error, 'code', type(error).__name__),
                        'original_reason': getattr(cause, 'code', type(cause).__name__) if cause else None})

    async def advance_after_expiry(self, task_id):
        """A closure failure interrupts its task, not every worker and live I/O."""
        try:
            await self.pipeline.advance(task_id)
        except Exception as exc:
            self.interrupt_task(task_id, exc, operation='expired_catalog_closure')

    def fail(self, job, error):
        repo, tid = (self.repository, job["task_id"])
        with repo.transaction() as conn:
            try:
                task = repo.task(conn, tid)
            except DomainError as exc:
                if exc.code in {"TASK_DELETED", "TASK_NOT_FOUND"}:
                    return
                raise
            if task["generation"] != job["generation"] or task["lifecycle"] in TERMINAL:
                return
            code = error.code if isinstance(error, DomainError) else type(error).__name__
            current_job = conn.execute(
                "SELECT status,lease_token FROM jobs WHERE job_id=?", (job["job_id"],)
            ).fetchone()
            if current_job and current_job["status"] == "succeeded":
                repo.enqueue(
                    conn, tid, "M13", "reconcile", {"after_job_id": job["job_id"], "reason": code}
                )
                repo.mutate_task(conn, tid, lifecycle="interrupted", resume_required=1)
                repo.event(
                    conn,
                    tid,
                    "orchestration_interrupted",
                    {"after_job_id": job["job_id"], "reason": code},
                )
                return
            if (
                not current_job
                or current_job["status"] != "running"
                or current_job["lease_token"] != job["lease_token"]
            ):
                return
            from astroquery_ai.runtime.throughput import DispatchDeferred

            if isinstance(error, DispatchDeferred):
                import time

                previous = conn.execute(
                    "SELECT coalesce(max(version),0) FROM objects WHERE task_id=? AND kind='dispatch_wait' AND object_id=?",
                    (tid, job["job_id"]),
                ).fetchone()[0]
                repo.put_object(
                    conn,
                    tid,
                    "dispatch_wait",
                    job["job_id"],
                    previous + 1,
                    {
                        "resource": error.resource,
                        "eligible_at": time.time() + error.seconds,
                        "wait_seconds": error.seconds,
                        "failed_attempt": False,
                    },
                )
                conn.execute(
                    "UPDATE jobs SET status='ready',reason='waiting_resource',attempt_count=attempt_count-1,lease_token=NULL,lease_until=NULL WHERE job_id=?",
                    (job["job_id"],),
                )
                repo.event(
                    conn,
                    tid,
                    "job_waiting_resource",
                    {
                        "job_id": job["job_id"],
                        "resource": error.resource,
                        "seconds": error.seconds,
                        "new_paid_attempt": False,
                    },
                )
                self.settle_pause(conn, tid)
                return
            result = self.application.failures.handle(conn, job, task, code, error)
            self.settle_pause(conn, tid)
            return result

    def settle_pause(self, conn, tid):
        # Both failures and resource deferrals drain an in-flight operation.
        # finish_job() alone only covers successful operations.
        repo = self.repository
        if repo.task(conn, tid)['lifecycle'] == 'pausing' and not conn.execute(
            "SELECT 1 FROM jobs WHERE task_id=? AND status='running' LIMIT 1", (tid,)
        ).fetchone():
            repo.mutate_task(conn, tid, lifecycle='paused', resume_required=1)
            repo.event(conn, tid, 'task_state_changed', {'lifecycle': 'paused'})

    async def stop(self, *, recover=True):
        self.stopping = True
        self.wake.set()
        if self.worker:
            try:
                await asyncio.wait_for(asyncio.shield(self.worker), timeout=5)
            except TimeoutError:
                self.worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.worker
            self.worker = None
        # A task-scoped material worker can close while sibling experiments
        # are still active in the same isolated repository. Global process
        # recovery is left to their common driver after all workers stop.
        if recover:
            self.repository.recover()
