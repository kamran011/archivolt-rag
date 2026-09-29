import json

import structlog
from openai import AsyncOpenAI

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.reranker.base import RerankerProvider

logger = structlog.get_logger()

BATCH_SIZE = 10

RERANK_PROMPT = """You are a relevance judge. Given a search query and a list of candidate passages, \
score each passage's relevance to the query on a scale of 0-10 (10 = directly answers the query, \
0 = completely irrelevant).

Query: {query}

Passages:
{passages}

Respond with ONLY a JSON array of objects: [{{"index": 0, "relevance_score": 8}}, ...]
One entry per passage, in the same order. No other text."""


class LLMReranker(RerankerProvider):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.RERANKER_MODEL
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        scored: list[tuple[RetrievedChunk, float]] = []

        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            try:
                scores = await self._score_batch(query, batch)
            except Exception as e:
                logger.warning("reranker_batch_failed_using_original_order", error=str(e))
                # Fall back to original retrieval scores for this batch
                scores = [c.score for c in batch]

            for chunk, score in zip(batch, scores, strict=True):
                scored.append((chunk, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)

        # model_copy keeps every field (authority, version, freshness...) intact;
        # rebuilding the chunk by hand silently drops fields added later.
        reranked = [chunk.model_copy(update={"score": score}) for chunk, score in scored[:top_k]]
        return reranked

    async def _score_batch(self, query: str, batch: list[RetrievedChunk]) -> list[float]:
        passages_text = "\n\n".join(
            f"[{i}] {chunk.content[:1000]}" for i, chunk in enumerate(batch)
        )
        prompt = RERANK_PROMPT.format(query=query, passages=passages_text)

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        raw = response.choices[0].message.content or "[]"
        raw_scores = self._parse_scores(raw, len(batch))
        # Normalize the model's 0-10 scale to 0-1 so downstream evidence
        # thresholds (calibrated for cosine/RRF scores) stay consistent.
        return [s / 10.0 for s in raw_scores]

    def _parse_scores(self, raw: str, expected_count: int) -> list[float]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            # Some models wrap in an object; handle both array and {"results": [...]} shapes
            data = json.loads(raw)
            if isinstance(data, dict):
                data = next(iter(data.values())) if data else []
            scores_by_index: dict[int, float] = {
                item["index"]: float(item["relevance_score"]) for item in data
            }
            return [scores_by_index.get(i, 0.0) for i in range(expected_count)]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning("reranker_parse_failed", error=str(e), raw=raw[:200])
            return [0.0] * expected_count
