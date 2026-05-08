from __future__ import annotations

import asyncio
import signal

from loguru import logger

from contentflow.db import init_db
from contentflow.scheduler import schedule_all_jobs, scheduler


async def _main() -> None:
    init_db()
    schedule_all_jobs()
    if not scheduler.running:
        raise RuntimeError("scheduler failed to start")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    logger.info("[SchedulerRunner] scheduler service started")
    await stop_event.wait()

    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("[SchedulerRunner] scheduler service stopped")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()