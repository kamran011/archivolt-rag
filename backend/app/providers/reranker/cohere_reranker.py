"""Provider reranker: Cohere Rerank v2 (a purpose-built cross-encoder API).

Cheaper and faster than asking an LLM to score passages, and its scores are already 0-1
relevance, so they slot into the same evidence thresholds.
"""

import httpx
import structlog

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.reranker.base import RerankerProvider

logger = structlog.get_logger()

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
MAX_DOC_CHARS = 2000


class CohereReranker(RerankerProvider):
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model or settings.COHERE_RERANK_MODEL
        self._api_key = api_key if api_key is not None else settings.COHERE_API_KEY
        self._client = client

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        try:
            scores = await self._scores(query, chunks)
        except Exception as e:
            # Never fail the request over reranking: keep the retrieval order/scores.
            logger.warning("cohere_rerank_failed_using_original_order", error=str(e))
            return chunks[:top_k]

        ranked = sorted(zip(chunks, scores, strict=True), key=lambda p: p[1], reverse=True)
        return [c.model_copy(update={"score": s}) for c, s in ranked[:top_k]]

    async def _scores(self, query: str, chunks: list[RetrievedChunk]) -> list[float]:
        if not self._api_key:
            raise RuntimeError("COHERE_API_KEY is not set")
        payload = {
            "model": self.model,
            "query": query,
            "documents": [c.content[:MAX_DOC_CHARS] for c in chunks],
            "top_n": len(chunks),
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            response = await self._client.post(COHERE_RERANK_URL, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(COHERE_RERANK_URL, json=payload, headers=headers)
        response.raise_for_status()

        by_index = {r["index"]: float(r["relevance_score"]) for r in response.json()["results"]}
        # Anything the API did not return scores 0, like the LLM reranker's parse fallback.
        return [by_index.get(i, 0.0) for i in range(len(chunks))]
