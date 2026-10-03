"""Ingestion as a durable job: enqueue, handler, and final-failure bookkeeping."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import update

from app.core.exceptions import IngestionError, NotFoundError, ValidationError
from app.domains.ingestion.service import ingestion_service
from app.domains.jobs import sessions
from app.domains.jobs.queue import job_queue
from app.domains.jobs.worker import JobHandler, PermanentJobError
from app.models.document import Document, DocumentStatus
from app.models.job import Job

logger = structlog.get_logger()

INGEST_KIND = "ingest_document"


def dedupe_key(doc_id: uuid.UUID) -> str:
    return f"doc:{doc_id}"


async def enqueue_ingestion(db, org_id: uuid.UUID, doc_id: uuid.UUID, *, reprocess: bool = False):
    """Queue ingestion in the caller's transaction, so the document row and its job commit
    together. One active job per document: asking again while one is queued or running
    returns that job instead of starting a second, concurrent ingestion."""
    return await job_queue.enqueue(
        db,
        INGEST_KIND,
        {"doc_id": str(doc_id), "reprocess": reprocess},
        org_id=org_id,
        dedupe_key=dedupe_key(doc_id),
    )


async def _mark_document_failed(doc_id: uuid.UUID, message: str) -> None:
    """Record failure in its own transaction (the ingest transaction was rolled back)."""
    try:
        async with sessions.new_session() as db:
            await db.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(status=DocumentStatus.failed, error_message=message[:2000])
            )
            await db.commit()
    except Exception as e:  # bookkeeping must never mask the original error
        logger.error("mark_failed_error", doc_id=str(doc_id), error=str(e))


async def _run(job: Job) -> None:
    doc_id = uuid.UUID(job.payload["doc_id"])
    reprocess = bool(job.payload.get("reprocess"))
    async with sessions.new_session() as db:
        try:
            if reprocess:
                await ingestion_service.reprocess_document(db, doc_id)
            else:
                await ingestion_service.ingest_document(db, doc_id)
            await db.commit()
        except (IngestionError, ValidationError, NotFoundError) as e:
            await db.rollback()
            # Bad file / missing record: retrying cannot help.
            raise PermanentJobError(str(e)) from e
        except Exception:
            await db.rollback()
            raise  # transient (provider down, DB blip, timeout): retried with backoff


async def _on_dead(job: Job, error: str) -> None:
    detail = error if job.attempts <= 1 else f"{error} (after {job.attempts} attempts)"
    await _mark_document_failed(uuid.UUID(job.payload["doc_id"]), detail)


ingestion_handler = JobHandler(run=_run, on_dead=_on_dead)
