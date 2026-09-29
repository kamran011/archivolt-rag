from abc import ABC, abstractmethod

from app.domains.retrieval.schemas import RetrievedChunk


class RerankerProvider(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError
