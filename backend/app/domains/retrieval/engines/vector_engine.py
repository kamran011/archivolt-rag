import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.engines.base import RetrievalEngine
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.models.chunk import Chunk
from app.models.document import Document
from app.providers.embeddings.registry import get_embedding_provider


class VectorRetrievalEngine(RetrievalEngine):
    async def search(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int,
        filters: RetrievalFilters | None = None,
        embedding_model: str = "text-embedding-3-small",
    ) -> list[RetrievedChunk]:
        provider = get_embedding_provider(embedding_model)
        query_embedding = await provider.embed_query(query)

        distance = Chunk.embedding.cosine_distance(query_embedding)
        stmt = (
            select(Chunk, Document, (1 - distance).label("score"))
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.organization_id == org_id,
                Chunk.knowledge_base_id.in_(kb_ids),
                Chunk.embedding.is_not(None),
            )
        )
        stmt = apply_common_filters(stmt, filters)
        stmt = stmt.order_by(distance).limit(top_k)

        result = await db.execute(stmt)
        rows = result.all()

        return [
            row_to_retrieved_chunk(chunk, document, score, "semantic")
            for chunk, document, score in rows
        ]
