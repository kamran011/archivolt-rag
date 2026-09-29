"""A small durable job queue on Postgres.

Interface (JobQueue) is narrow on purpose so a real broker can replace the Postgres
implementation later without touching callers. The Postgres version claims work with
FOR UPDATE SKIP LOCKED, so any number of workers/processes can run concurrently and no job is
ever run twice at once.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import Job

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(attempt: int) -> float:
    """Delay before retry number `attempt` (1-based): base * 2^(attempt-1), capped."""
    return min(settings.JOB_RETRY_BASE_S * (2 ** max(0, attempt - 1)), settings.JOB_RETRY_MAX_S)


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(
        self,
        db: AsyncSession,
        kind: str,
        payload: dict,
        *,
        org_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
        delay_s: float = 0.0,
    ) -> Job: ...

    @abstractmethod
    async def claim(
        self, db: AsyncSession, worker_id: str, *, kinds: list[str] | None = None,
        job_id: uuid.UUID | None = None, limit: int = 1,
    ) -> list[Job]: ...

    @abstractmethod
    async def succeed(self, db: AsyncSession, job: Job) -> None: ...

    @abstractmethod
    async def fail(self, db: AsyncSession, job: Job, error: str, *, permanent: bool) -> str:
        """Record a failed attempt. Returns the new status: queued (will retry), failed
        (permanent error) or dead (retries exhausted)."""

    @abstractmethod
    async def reclaim_orphans(self, db: AsyncSession) -> int: ...


class PostgresJobQueue(JobQueue):
    async def enqueue(
        self,
        db: AsyncSession,
        kind: str,
        payload: dict,
        *,
        org_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
        delay_s: float = 0.0,
    ) -> Job:
        """Add a job in the caller's transaction (so it commits atomically with, say, the
        document row it refers to). If an active job with the same (kind, dedupe_key)
        exists, that job is returned instead of adding a duplicate."""
        values = {
            "organization_id": org_id,
            "kind": kind,
            "dedupe_key": dedupe_key,
            "payload": payload,
            "status": "queued",
            "attempts": 0,
            "max_attempts": max_attempts or settings.JOB_MAX_ATTEMPTS,
            "run_after": _now() + timedelta(seconds=delay_s),
        }
        stmt = pg_insert(Job).values(**values, id=uuid.uuid4())
        if dedupe_key is not None:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[Job.kind, Job.dedupe_key],
                index_where=Job.status.in_(("queued", "running")) & Job.dedupe_key.is_not(None),
            )
        result = await db.execute(stmt.returning(Job.id))
        job_id = result.scalar_one_or_none()
        if job_id is None:  # deduplicated
            existing = await db.execute(
                select(Job).where(
                    Job.kind == kind,
                    Job.dedupe_key == dedupe_key,
                    Job.status.in_(("queued", "running")),
                )
            )
            return existing.scalars().one()
        return (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()

    async def claim(
        self,
        db: AsyncSession,
        worker_id: str,
        *,
        kinds: list[str] | None = None,
        job_id: uuid.UUID | None = None,
        limit: int = 1,
    ) -> list[Job]:
        stmt = select(Job).where(Job.status == "queued", Job.run_after <= _now())
        if job_id is not None:
            stmt = stmt.where(Job.id == job_id)
        if kinds:
            stmt = stmt.where(Job.kind.in_(kinds))
        stmt = stmt.order_by(Job.run_after, Job.created_at).limit(limit).with_for_update(
            skip_locked=True
        )
        jobs = list((await db.execute(stmt)).scalars().all())
        for job in jobs:
            job.status = "running"
            job.attempts += 1
            job.locked_at = _now()
            job.locked_by = worker_id
        await db.flush()
        return jobs

    async def succeed(self, db: AsyncSession, job: Job) -> None:
        job.status, job.finished_at = "succeeded", _now()
        job.locked_at = job.locked_by = None
        job.last_error = None
        await db.flush()

    async def fail(self, db: AsyncSession, job: Job, error: str, *, permanent: bool) -> str:
        job.last_error = error[:2000]
        job.locked_at = job.locked_by = None
        if permanent:
            job.status, job.finished_at = "failed", _now()
        elif job.attempts >= job.max_attempts:
            job.status, job.finished_at = "dead", _now()
        else:
            job.status = "queued"
            job.run_after = _now() + timedelta(seconds=backoff_seconds(job.attempts))
        await db.flush()
        return job.status

    async def reclaim_orphans(self, db: AsyncSession) -> int:
        """'running' jobs whose worker vanished (locked longer than JOB_LOCK_TIMEOUT_S):
        re-queue them, or mark them dead if they already used all their attempts."""
        cutoff = _now() - timedelta(seconds=settings.JOB_LOCK_TIMEOUT_S)
        stale = (
            await db.execute(
                select(Job).where(Job.status == "running", Job.locked_at < cutoff)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for job in stale:
            job.last_error = "worker lost (job was running but its lock expired)"
            job.locked_at = job.locked_by = None
            if job.attempts >= job.max_attempts:
                job.status, job.finished_at = "dead", _now()
            else:
                job.status, job.run_after = "queued", _now()
        await db.flush()
        if stale:
            logger.warning("reclaimed_orphaned_jobs", count=len(stale))
        return len(stale)


job_queue: JobQueue = PostgresJobQueue()
