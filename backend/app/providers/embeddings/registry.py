from functools import lru_cache

from app.config import settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.openai_embeddings import OpenAIEmbeddingProvider


@lru_cache(maxsize=8)
def get_embedding_provider(model_name: str) -> EmbeddingProvider:
    # All current models route to OpenAI; extend this when adding providers
    # (e.g. Cohere, Voyage) keyed off model name prefixes.
    provider: EmbeddingProvider = OpenAIEmbeddingProvider(model_name=model_name)
    if settings.ENABLE_EMBEDDING_CACHE:
        from app.core.cache import get_cache
        from app.core.cached_providers import CachedEmbeddingProvider

        provider = CachedEmbeddingProvider(provider, get_cache(), settings.EMBEDDING_CACHE_TTL_S)
    return provider
