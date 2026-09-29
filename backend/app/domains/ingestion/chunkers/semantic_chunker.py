"""Semantic chunking: split oversized sections where the topic shifts.

Sentences are embedded and a boundary is placed where the distance between consecutive
sentences is unusually high (above a percentile of that section's own distances).
Costs one embedding per sentence of each *oversized* section only.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable

from app.domains.ingestion.chunkers.planned_chunker import PlannedChunker

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

BREAKPOINT_PERCENTILE = 85
MIN_SENTENCES_PER_GROUP = 2


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 if na == 0 or nb == 0 else 1.0 - dot / (na * nb)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def semantic_groups(
    sentences: list[str],
    embeddings: list[list[float]],
    *,
    percentile: float = BREAKPOINT_PERCENTILE,
    min_sentences: int = MIN_SENTENCES_PER_GROUP,
) -> list[list[str]]:
    """Pure function: group sentences, breaking at the largest embedding-distance jumps."""
    if len(sentences) != len(embeddings):
        raise ValueError("one embedding per sentence is required")
    if len(sentences) <= min_sentences:
        return [list(sentences)]

    distances = [
        _cosine_distance(embeddings[i], embeddings[i + 1]) for i in range(len(sentences) - 1)
    ]
    threshold = _percentile(distances, percentile)

    groups: list[list[str]] = [[sentences[0]]]
    for i, d in enumerate(distances):
        big_jump = d > threshold
        if big_jump and len(groups[-1]) >= min_sentences:
            groups.append([])
        groups[-1].append(sentences[i + 1])
    if len(groups) > 1 and len(groups[-1]) < min_sentences:
        groups[-2].extend(groups.pop())  # no orphan single-sentence tail
    return groups


class SemanticChunker(PlannedChunker):
    marker = "semantic_split"

    def __init__(self, embed: EmbedFn) -> None:
        super().__init__()
        self._embed = embed
        self.embedding_tokens = 0  # for cost accounting

    async def _plan_groups(self, sentences: list[str]) -> list[list[str]] | None:
        embeddings = await self._embed(sentences)
        self.embedding_tokens += sum(self.count_tokens(s) for s in sentences)
        return semantic_groups(sentences, embeddings)
