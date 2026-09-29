import uuid

import structlog

from app.core.database import AsyncSessionLocal
from app.domains.ingestion.service import ingestion_service

logger = structlog.get_logger()


async def run_ingestion(doc_id: uuid.UUID) -> None:
    """Wrapper for use with FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await ingestion_service.ingest_document(db, doc_id)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("background_ingestion_failed", doc_id=str(doc_id), error=str(e))
