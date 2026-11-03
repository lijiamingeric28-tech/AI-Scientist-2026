"""CLI uses the same application service and explicit actions as the Web UI."""

from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.lifecycle import InstanceLock
from astroquery_ai.runtime.scheduler import Scheduler

from astroquery_ai.runtime.paths import data_root


def main() -> int:
    parser = argparse.ArgumentParser(description="AstroQuery AI：持久化科研查询")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--task", help="查看现有任务，不自动恢复执行")
    parser.add_argument("--action-file", type=Path, help="对--task提交同Web协议的草稿操作JSON")
    parser.add_argument("--control", choices=["pause", "continue", "cancel", "retry"])
    parser.add_argument("--import-registry", type=Path)
    parser.add_argument("--import-knowledge", type=Path)
    parser.add_argument("--import-credentials", type=Path, help="从本地百炼CSV导入密钥；不会回显")
    args = parser.parse_args()
    if not any(
        (
            args.query,
            args.task,
            args.import_registry,
            args.import_knowledge,
            args.import_credentials,
        )
    ):
        parser.print_help()
        return 0
    args.data_root = data_root(args.data_root)
    with InstanceLock(args.data_root):
        app = Application(args.data_root)
        app.repository.recover()
        if args.import_credentials:
            result = app.configuration.import_csv(args.import_credentials)
            print(
                json.dumps(
                    {
                        "saved_revision": result["saved_revision"],
                        "restart_required": result["restart_required"],
                    },
                    ensure_ascii=False,
                )
            )
        elif args.import_registry:
            print(json.dumps(app.registry.import_release(args.import_registry), ensure_ascii=False))
        elif args.import_knowledge:
            print(
                json.dumps(app.knowledge.import_release(args.import_knowledge), ensure_ascii=False)
            )
        elif args.task:
            if args.action_file:
                app.draft_action(args.task, loads(args.action_file.read_bytes()))
            elif args.control:
                current = app.repository.get_task(args.task)
                app.repository.control(
                    args.task,
                    args.control,
                    str(uuid4()),
                    current["revision"],
                    finalizer=app.delivery.seal,
                )
            if args.action_file or args.control == "continue":
                asyncio.run(_until_idle(app, args.task))
            print(json.dumps(app.view(args.task), ensure_ascii=False, indent=2))
        elif args.query:
            task = app.create(args.query, str(uuid4()))
            asyncio.run(_until_idle(app, task["task_id"]))
            print(json.dumps(app.view(task["task_id"]), ensure_ascii=False, indent=2))
        else:
            parser.print_help()
    return 0


async def _until_idle(app, task_id):
    from astroquery_ai.runtime.errors import DomainError
    try:
        await asyncio.to_thread(app.registry.load)
    except DomainError:
        pass  # The ordinary prepare job retains the precise registry error.
    scheduler = Scheduler(app, task_id=task_id)
    await scheduler.start()
    try:
        while True:
            task = app.repository.get_task(task_id)
            if task['lifecycle'] in {'completed', 'cancelled', 'failed', 'budget_exhausted',
                                     'definition_invalidated', 'paused', 'interrupted',
                                     'waiting_review', 'waiting_input'}:
                return
            with app.repository.read() as conn:
                active = conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('ready','running','waiting_dependency','awaiting_review') LIMIT 1", (task_id,)).fetchone()
            if not active:
                return
            await asyncio.sleep(.1)
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    raise SystemExit(main())
