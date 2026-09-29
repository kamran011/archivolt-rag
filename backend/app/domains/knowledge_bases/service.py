import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.domains.knowledge_bases.schemas import KBCreate, KBStats, KBUpdate
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KBStatus, KnowledgeBase

logger = structlog.get_logger()


class KnowledgeBaseService:
    async def create(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        data: KBCreate,
    ) -> KnowledgeBase:
        kb = KnowledgeBase(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            chunk_strategy=data.chunk_strategy,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            embedding_model=data.embedding_model,
            cag_enabled=data.cag_enabled,
        )
        db.add(kb)
        await db.flush()
        logger.info("kb_created", kb_id=str(kb.id), org_id=str(org_id))
        return kb

    async def get(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> KnowledgeBase:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.organization_id == org_id,  # tenant filter — always present
        )
        result = await db.execute(stmt)
        kb = result.scalar_one_or_none()
        if not kb:
            raise NotFoundError(f"Knowledge base {kb_id} not found")
        return kb

    async def list(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        include_archived: bool = False,
    ) -> list[KnowledgeBase]:
        stmt = select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
        if not include_archived:
            stmt = stmt.where(KnowledgeBase.status == KBStatus.active)
        stmt = stmt.order_by(KnowledgeBase.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
        data: KBUpdate,
    ) -> KnowledgeBase:
        kb = await self.get(db, org_id, kb_id)
        if data.name is not None:
            kb.name = data.name
        if data.description is not None:
            kb.description = data.description
        if data.status is not None:
            kb.status = data.status
        if data.cag_enabled is not None:
            kb.cag_enabled = data.cag_enabled
        await db.flush()
        return kb

    async def archive(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> KnowledgeBase:
        kb = await self.get(db, org_id, kb_id)
        kb.status = KBStatus.archived
        await db.flush()
        return kb

    async def get_stats(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> KBStats:
        # Verify KB belongs to org
        await self.get(db, org_id, kb_id)

        doc_stmt = select(
            func.count(Document.id).label("total"),
            func.count(Document.id).filter(Document.status == DocumentStatus.ready).label("ready"),
            func.count(Document.id).filter(Document.status == DocumentStatus.failed).label("failed"),
            func.sum(Document.chunk_count).label("chunks"),
        ).where(Document.knowledge_base_id == kb_id, Document.organization_id == org_id)

        result = await db.execute(doc_stmt)
        row = result.one()

        total = row.total or 0
        ready = row.ready or 0
        failed = row.failed or 0
        pending = total - ready - failed

        return KBStats(
            document_count=total,
            chunk_count=row.chunks or 0,
            total_tokens=0,  # populated once chunk token tracking is wired in 1D
            ready_documents=ready,
            failed_documents=failed,
            pending_documents=pending,
        )

    async def increment_document_count(
        self, db: AsyncSession, kb_id: uuid.UUID, delta: int = 1
    ) -> None:
        kb = await db.get(KnowledgeBase, kb_id)
        if kb:
            kb.document_count += delta
            await db.flush()


kb_service = KnowledgeBaseService()
