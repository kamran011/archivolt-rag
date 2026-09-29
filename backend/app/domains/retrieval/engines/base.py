import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk


class RetrievalEngine(ABC):
    @abstractmethod
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
        raise NotImplementedError
