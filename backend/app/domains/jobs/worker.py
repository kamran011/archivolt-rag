"""Job handlers and the worker that runs them.

A handler either returns (success), raises PermanentJobError (do not retry: bad input) or any
other exception (transient: retried with backoff until max_attempts, then the job is dead and
the handler's on_dead hook runs so user-visible state can be finalized). Each attempt runs in
its own DB session under a timeout.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.jobs.queue import JobQueue, job_queue
from app.models.job import Job

logger = structlog.get_logger()

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PermanentJobError(Exception):
    """The job can never succeed (invalid input, missing record): fail it, don't retry."""


@dataclass
class JobHandler:
    run: Callable[[Job], Awaitable[None]]
    # Called once when the job ends without success (permanent failure or retries exhausted).
    on_dead: Callable[[Job, str], Awaitable[None]] | None = None


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return list(self._handlers)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class Worker:
    def __init__(
        self,
        session_factory: SessionFactory,
        registry: HandlerRegistry,
        queue: JobQueue = job_queue,
        worker_id: str | None = None,
    ) -> None:
        self._session = session_factory
        self.registry = registry
        self.queue = queue
        self.worker_id = worker_id or default_worker_id()

    async def run_job(self, job_id: uuid.UUID) -> str | None:
        """Claim and execute one specific job now (the fast path right after enqueue).
        Returns the resulting status, or None if it was not claimable (already running,
        finished, or scheduled for later)."""
        async with self._session() as db:
            claimed = await self.queue.claim(
                db, self.worker_id, job_id=job_id, kinds=self.registry.kinds()
            )
            await db.commit()
        return await self._execute(claimed[0]) if claimed else None

    async def run_once(self) -> str | None:
        """Claim and execute the next due job. None when there is nothing to do."""
        async with self._session() as db:
            claimed = await self.queue.claim(db, self.worker_id, kinds=self.registry.kinds())
            await db.commit()
        return await self._execute(claimed[0]) if claimed else None

    async def run_until_idle(self, max_jobs: int = 1000) -> int:
        done = 0
        while done < max_jobs and await self.run_once() is not None:
            done += 1
        return done

    async def _execute(self, job: Job) -> str:
        handler = self.registry.get(job.kind)
        if handler is None:  # cannot happen through claim(kinds=...), but never crash on it
            return await self._finish(job, "no handler registered", permanent=True, handler=None)
        try:
            await asyncio.wait_for(handler.run(job), timeout=settings.JOB_TIMEOUT_S)
        except PermanentJobError as e:
            return await self._finish(job, str(e), permanent=True, handler=handler)
        except TimeoutError:
            return await self._finish(
                job, f"timed out after {settings.JOB_TIMEOUT_S}s", permanent=False, handler=handler
            )
        except Exception as e:
            logger.warning("job_attempt_failed", kind=job.kind, job_id=str(job.id), error=str(e))
            return await self._finish(job, str(e), permanent=False, handler=handler)

        async with self._session() as db:
            fresh = await db.get(Job, job.id)
            await self.queue.succeed(db, fresh)
            await db.commit()
        return "succeeded"

    async def _finish(
        self, job: Job, error: str, *, permanent: bool, handler: JobHandler | None
    ) -> str:
        async with self._session() as db:
            fresh = await db.get(Job, job.id)
            status = await self.queue.fail(db, fresh, error, permanent=permanent)
            await db.commit()
        if status in ("failed", "dead") and handler and handler.on_dead:
            try:
                await handler.on_dead(job, error)
            except Exception as e:  # finalizing user-visible state must not crash the worker
                logger.error("job_on_dead_failed", job_id=str(job.id), error=str(e))
        return status

    async def run_forever(self) -> None:
        """Poll for due jobs and reclaim orphans until cancelled."""
        logger.info("job_worker_started", worker=self.worker_id, kinds=self.registry.kinds())
        idle_ticks = 0
        try:
            while True:
                try:
                    if await self.run_once() is not None:
                        idle_ticks = 0
                        continue
                    idle_ticks += 1
                    if idle_ticks % 10 == 1:  # also on the first idle tick after startup
                        async with self._session() as db:
                            await self.queue.reclaim_orphans(db)
                            await db.commit()
                except Exception as e:  # keep the loop alive across transient DB errors
                    logger.error("job_worker_iteration_failed", error=str(e))
                await asyncio.sleep(settings.JOB_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("job_worker_stopped", worker=self.worker_id)
            raise
