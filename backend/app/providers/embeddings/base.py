from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    model_name: str
    dimensions: int

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents/chunks."""
        raise NotImplementedError

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Embed a single search query."""
        raise NotImplementedError
