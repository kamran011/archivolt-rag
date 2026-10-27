"""Per-request memo of query embeddings.

A RAG request searches several query variants (the question, its rewrite, alternative
phrasings) and may repeat a search with another strategy. Without a memo each search
embeds its query in its own API call, one after another. `prefetch` embeds every variant in
one batched call up front; `embed_query` then serves them from the memo.

Scoped to the current request with a ContextVar, and keyed by (embedding model, query), so
a vector is only reused for the exact same text and model. When no memo is active (search
API, agent tools, debugger) or a query was not prefetched, `embed_query` behaves exactly
like `provider.embed_query`.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

import structlog

from app.providers.embeddings.base import EmbeddingProvider

logger = structlog.get_logger()

_memo: ContextVar[dict[tuple[str, str], list[float]] | None] = ContextVar(
    "query_embedding_memo", default=None
)


def _model(provider: EmbeddingProvider) -> str:
    return getattr(provider, "model_name", None) or type(provider).__name__


@contextmanager
def query_embedding_memo():
    """Activate an empty memo for the code inside the block (one RAG request)."""
    token = _memo.set({})
    try:
        yield
    finally:
        _memo.reset(token)


async def prefetch(provider: EmbeddingProvider, queries: list[str]) -> None:
    """Embed every not-yet-memoized query in one batched call. Best effort: on failure the
    searches simply embed their own queries as before."""
    memo = _memo.get()
    if memo is None:
        return
    model = _model(provider)
    missing = list(dict.fromkeys(q for q in queries if (model, q) not in memo))
    if not missing:
        return
    try:
        vectors = await provider.embed_texts(missing)
    except Exception as e:  # the per-search path still embeds (and reports errors) normally
        logger.warning("query_embedding_prefetch_failed", error=str(e))
        return
    for query, vector in zip(missing, vectors, strict=True):
        memo[(model, query)] = vector


async def embed_query(provider: EmbeddingProvider, query: str) -> list[float]:
    memo = _memo.get()
    if memo is not None:
        hit = memo.get((_model(provider), query))
        if hit is not None:
            return hit
    vector = await provider.embed_query(query)
    if memo is not None:
        memo[(_model(provider), query)] = vector
    return vector
