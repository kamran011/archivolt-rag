from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import String, and_, cast, exists, func, update

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.document import Document, DocumentStatus
from app.models.job import Job

logger = structlog.get_logger()

IN_FLIGHT = (
    DocumentStatus.pending,
    DocumentStatus.parsing,
    DocumentStatus.chunking,
    DocumentStatus.embedding,
)


async def recover_stuck_ingestions(older_than_minutes: int | None = None) -> int:
    """Mark documents left mid-ingestion with NO active job (e.g. from before jobs existed,
    or a lost job row) as failed so users can reprocess them. A document whose job is queued
    or running is left alone: it is waiting its turn or being retried, not stuck."""
    minutes = older_than_minutes or settings.INGESTION_STUCK_AFTER_MINUTES
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    has_active_job = exists().where(
        and_(
            Job.kind == "ingest_document",
            Job.status.in_(("queued", "running")),
            Job.dedupe_key == func.concat("doc:", cast(Document.id, String)),
        )
    )
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Document)
            .where(Document.status.in_(IN_FLIGHT), Document.updated_at < cutoff, ~has_active_job)
            .values(
                status=DocumentStatus.failed,
                error_message="Ingestion was interrupted before completing. Reprocess to retry.",
            )
        )
        await db.commit()
    count = result.rowcount or 0
    if count:
        logger.warning("recovered_stuck_ingestions", count=count)
    return count
