from app.config import settings
from app.providers.reranker.base import RerankerProvider
from app.providers.reranker.cohere_reranker import CohereReranker
from app.providers.reranker.llm_reranker import LLMReranker


class NoReranker(RerankerProvider):
    """Keeps retrieval order and scores (top_k only). For A/B comparison in evals."""

    async def rerank(self, query, chunks, top_k):
        return chunks[:top_k]


def get_reranker(provider: str | None = None) -> RerankerProvider:
    name = (provider or settings.RERANKER_PROVIDER).lower()
    if name == "cohere":
        return CohereReranker()
    if name == "none":
        return NoReranker()
    if name == "llm":
        return LLMReranker()
    raise ValueError(f"Unknown RERANKER_PROVIDER '{name}' (expected llm, cohere or none)")
