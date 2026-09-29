from functools import lru_cache

from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.openai_embeddings import OpenAIEmbeddingProvider


@lru_cache(maxsize=8)
def get_embedding_provider(model_name: str) -> EmbeddingProvider:
    # All current models route to OpenAI; extend this when adding providers
    # (e.g. Cohere, Voyage) keyed off model name prefixes.
    return OpenAIEmbeddingProvider(model_name=model_name)
