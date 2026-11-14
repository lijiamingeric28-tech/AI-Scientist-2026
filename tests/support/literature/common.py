"""Offline literature fixtures used by the retrieval regression suite."""


async def claim_module_job(app,tid,owner,*,lease_seconds=1800):
    """A full worker pool is a resource wait, not a missing material job."""
    import asyncio
    while True:
        job=app.repository.claim_job(owner,task_id=tid,lease_seconds=lease_seconds)
        if job is not None:return job
        with app.repository.read() as c:
            task=app.repository.task(c,tid)
            ready=c.execute("select count(*) from jobs where task_id=? and status='ready'",(tid,)).fetchone()[0]
        if not ready or task['lifecycle'] not in {'queued','running','clarifying'}:
            raise RuntimeError('No resumable ready module job: '+str((tid,task['lifecycle'])))
        await asyncio.sleep(app.repository.dispatch_delay(default=1))
