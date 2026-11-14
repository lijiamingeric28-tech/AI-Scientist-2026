"""Keep parallel I/O children within the lifetime of their owning job."""
import asyncio


async def gather_scoped(*coroutines):
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # gather propagates the first exception without cancelling siblings.
        # Drain them before the coordinator releases its lease or retries.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
