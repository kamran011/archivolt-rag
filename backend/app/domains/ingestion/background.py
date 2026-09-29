import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import update

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.ingestion.service import ingestion_service
from app.models.document import Document, DocumentStatus

logger = structlog.get_logger()

IN_FLIGHT = (
    DocumentStatus.pending,
    DocumentStatus.parsing,
    DocumentStatus.chunking,
    DocumentStatus.embedding,
)


async def _mark_failed(doc_id: uuid.UUID, message: str) -> None:
    """Record failure in its own transaction. The ingest transaction is rolled back on
    error, which would otherwise erase the 'failed' status and leave the document
    stuck in an in-flight state."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(status=DocumentStatus.failed, error_message=message[:2000])
            )
            await db.commit()
    except Exception as e:  # never let bookkeeping mask the original error
        logger.error("mark_failed_error", doc_id=str(doc_id), error=str(e))


async def run_ingestion(doc_id: uuid.UUID, reprocess: bool = False) -> None:
    """Wrapper for use with FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            if reprocess:
                await ingestion_service.reprocess_document(db, doc_id)
            else:
                await ingestion_service.ingest_document(db, doc_id)
            await db.commit()
            return
        except Exception as e:
            await db.rollback()
            logger.error("background_ingestion_failed", doc_id=str(doc_id), error=str(e))
            error = str(e)
    await _mark_failed(doc_id, error)


async def recover_stuck_ingestions(older_than_minutes: int | None = None) -> int:
    """Mark documents left mid-ingestion (e.g. the process died) as failed so users can
    reprocess them. The age threshold avoids touching another worker's live jobs."""
    minutes = older_than_minutes or settings.INGESTION_STUCK_AFTER_MINUTES
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Document)
            .where(Document.status.in_(IN_FLIGHT), Document.updated_at < cutoff)
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
