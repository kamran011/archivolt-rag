"""Dedicated job worker: `python -m app.worker`.

Run this instead of (or alongside) the in-process worker when ingestion should not share a
process with the API. Set JOB_WORKER_IN_PROCESS=false on the API in that case. Any number of
workers may run at once; jobs are claimed with FOR UPDATE SKIP LOCKED.
"""

import asyncio

from app.core.logging import configure_logging
from app.domains.jobs.setup import worker


async def main() -> None:
    configure_logging()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
