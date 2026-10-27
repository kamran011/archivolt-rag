"""Cache wrappers for embedding and reranker providers.

Both caches key on immutable inputs (text hash / chunk ids, which change whenever content
changes), so there is nothing to invalidate: a stale entry can never be hit.
"""

from __future__ import annotations

import hashlib

from app.core.cache import Cache, safe
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.reranker.base import RerankerProvider


def _h(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class CachedEmbeddingProvider(EmbeddingProvider):
    def __init__(self, inner: EmbeddingProvider, cache: Cache, ttl: int) -> None:
        self._inner, self._cache, self._ttl = inner, cache, ttl
        self.model_name = inner.model_name
        self.dimensions = inner.dimensions

    def __getattr__(self, name):  # tokens counters etc. of the wrapped provider
        return getattr(self._inner, name)

    def _key(self, text: str) -> str:
        return f"emb:{self.model_name}:{_h(text)}"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = []
        for text in texts:
            results.append(await safe(self._cache.get_json(self._key(text))))
        misses = [i for i, v in enumerate(results) if v is None]
        if misses:
            vectors = await self._inner.embed_texts([texts[i] for i in misses])
            for i, vector in zip(misses, vectors, strict=True):
                results[i] = vector
                await safe(self._cache.set_json(self._key(texts[i]), vector, self._ttl))
        return results  # type: ignore[return-value]

    async def embed_query(self, query: str) -> list[float]:
        key = self._key(query)
        hit = await safe(self._cache.get_json(key))
        if hit is not None:
            return hit
        vector = await self._inner.embed_query(query)
        await safe(self._cache.set_json(key, vector, self._ttl))
        return vector


class CachedReranker(RerankerProvider):
    def __init__(self, inner: RerankerProvider, cache: Cache, ttl: int) -> None:
        self._inner, self._cache, self._ttl = inner, cache, ttl

    async def rerank(self, query, chunks, top_k):
        key = "rerank:" + _h(
            type(self._inner).__name__, " ".join(query.lower().split()), str(top_k),
            *sorted(str(c.chunk_id) for c in chunks),
        )
        hit = await safe(self._cache.get_json(key))
        if hit:  # an empty entry is never a valid rerank of a non-empty candidate list
            by_id = {str(c.chunk_id): c for c in chunks}
            if all(cid in by_id for cid, _ in hit):
                return [by_id[cid].model_copy(update={"score": score}) for cid, score in hit]
        from app.providers.reranker.llm_reranker import rerank_degraded

        token = rerank_degraded.set(False)
        try:
            result: list[RetrievedChunk] = await self._inner.rerank(query, chunks, top_k)
            degraded = rerank_degraded.get()
        finally:
            rerank_degraded.reset(token)
        # A fallback result (provider failed) is served once but never cached, so one bad
        # call cannot keep failing the same question for the whole TTL.
        if result and not degraded:
            await safe(
                self._cache.set_json(key, [[str(c.chunk_id), c.score] for c in result], self._ttl)
            )
        return result
