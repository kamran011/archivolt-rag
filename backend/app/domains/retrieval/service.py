import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.engines.hybrid_engine import HybridRetrievalEngine
from app.domains.retrieval.engines.keyword_engine import KeywordRetrievalEngine
from app.domains.retrieval.engines.tree_engine import TreeRetrievalEngine
from app.domains.retrieval.engines.vector_engine import VectorRetrievalEngine
from app.domains.retrieval.schemas import RetrievalRequest, RetrievalResult

_ENGINES = {
    "semantic": VectorRetrievalEngine(),
    "keyword": KeywordRetrievalEngine(),
    "hybrid": HybridRetrievalEngine(),
    "tree": TreeRetrievalEngine(),
}


class RetrievalService:
    async def retrieve(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        request: RetrievalRequest,
        embedding_model: str = "text-embedding-3-small",
        scope: AccessScope | None = None,
    ) -> RetrievalResult:
        strategy = request.strategy

        start = time.perf_counter()
        chunks = await _ENGINES[strategy].search(
            db,
            org_id,
            request.query,
            request.knowledge_base_ids,
            request.top_k,
            request.filters,
            embedding_model,
            scope,
        )
        if strategy == "tree" and not chunks:
            # Nothing to navigate (no trees / navigation failed): degrade to hybrid.
            strategy = "hybrid"
            chunks = await _ENGINES[strategy].search(
                db,
                org_id,
                request.query,
                request.knowledge_base_ids,
                request.top_k,
                request.filters,
                embedding_model,
                scope,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000

        return RetrievalResult(
            chunks=chunks,
            query=request.query,
            strategy=strategy,
            total_candidates=len(chunks),
            retrieval_time_ms=round(elapsed_ms, 2),
        )


retrieval_service = RetrievalService()
