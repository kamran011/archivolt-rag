import asyncio

import structlog
from openai import AsyncOpenAI, APIError, RateLimitError

from app.config import settings
from app.core.exceptions import ProviderError
from app.providers.embeddings.base import EmbeddingProvider

logger = structlog.get_logger()

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float]] = []
        batch_size = settings.EMBEDDING_BATCH_SIZE

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._embed_with_retry(batch)
            results.extend(embeddings)

        return results

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self._embed_with_retry([query])
        return embeddings[0]

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        backoff = INITIAL_BACKOFF
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self.model_name,
                    input=texts,
                )
                return [item.embedding for item in response.data]
            except RateLimitError as e:
                last_error = e
                logger.warning("embedding_rate_limited", attempt=attempt, backoff=backoff)
                await asyncio.sleep(backoff)
                backoff *= 2
            except APIError as e:
                last_error = e
                logger.error("embedding_api_error", error=str(e), attempt=attempt)
                await asyncio.sleep(backoff)
                backoff *= 2

        raise ProviderError(f"Embedding generation failed after {MAX_RETRIES} attempts: {last_error}")
