import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.engines.base import RetrievalEngine
from app.domains.retrieval.engines.keyword_engine import KeywordRetrievalEngine
from app.domains.retrieval.engines.vector_engine import VectorRetrievalEngine
from app.domains.retrieval.rrf import reciprocal_rank_fusion
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk


class HybridRetrievalEngine(RetrievalEngine):
    def __init__(self) -> None:
        self._vector = VectorRetrievalEngine()
        self._keyword = KeywordRetrievalEngine()

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
        # Retrieve a wider candidate pool from each engine before fusing,
        # so RRF has enough signal to surface cross-method agreement.
        candidate_k = max(top_k * 2, 20)

        # One AsyncSession cannot run two statements at once (asyncpg: "another operation is
        # in progress"; SQLAlchemy: "provisioning a new connection"). This used to be a
        # gather() that only worked because the embedding network call happened to delay
        # the vector query. Run them one after the other.
        semantic_results = await self._vector.search(
            db, org_id, query, kb_ids, candidate_k, filters, embedding_model, scope
        )
        keyword_results = await self._keyword.search(
            db, org_id, query, kb_ids, candidate_k, filters, embedding_model, scope
        )

        fused = reciprocal_rank_fusion([semantic_results, keyword_results])
        return fused[:top_k]
