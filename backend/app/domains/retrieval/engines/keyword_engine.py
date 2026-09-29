import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.engines.base import RetrievalEngine
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.models.chunk import Chunk
from app.models.document import Document


class KeywordRetrievalEngine(RetrievalEngine):
    async def search(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int,
        filters: RetrievalFilters | None = None,
        embedding_model: str = "text-embedding-3-small",
        scope: AccessScope | None = None,
    ) -> list[RetrievedChunk]:
        tsquery = func.plainto_tsquery("english", query)
        rank = func.ts_rank_cd(Chunk.fts_vector, tsquery)

        stmt = (
            select(Chunk, Document, rank.label("score"))
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.organization_id == org_id,
                Chunk.knowledge_base_id.in_(kb_ids),
                Chunk.fts_vector.op("@@")(tsquery),
            )
        )
        stmt = apply_common_filters(stmt, filters, scope)
        stmt = stmt.order_by(rank.desc()).limit(top_k)

        result = await db.execute(stmt)
        rows = result.all()

        return [
            row_to_retrieved_chunk(chunk, document, score, "keyword")
            for chunk, document, score in rows
        ]
