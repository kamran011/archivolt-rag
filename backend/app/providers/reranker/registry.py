from app.config import settings
from app.providers.reranker.base import RerankerProvider
from app.providers.reranker.cohere_reranker import CohereReranker
from app.providers.reranker.llm_reranker import LLMReranker


class NoReranker(RerankerProvider):
    """Keeps retrieval order and scores (top_k only). For A/B comparison in evals."""

    async def rerank(self, query, chunks, top_k):
        return chunks[:top_k]


def get_reranker(provider: str | None = None) -> RerankerProvider:
    reranker = _build_reranker(provider)
    if settings.ENABLE_RERANK_CACHE and not isinstance(reranker, NoReranker):
        from app.core.cache import get_cache
        from app.core.cached_providers import CachedReranker

        return CachedReranker(reranker, get_cache(), settings.RERANK_CACHE_TTL_S)
    return reranker


def _build_reranker(provider: str | None = None) -> RerankerProvider:
    name = (provider or settings.RERANKER_PROVIDER).lower()
    if name == "cohere":
        return CohereReranker()
    if name == "none":
        return NoReranker()
    if name == "llm":
        return LLMReranker()
    raise ValueError(f"Unknown RERANKER_PROVIDER '{name}' (expected llm, cohere or none)")
