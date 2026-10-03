"""Base for chunkers that decide *where to split oversized sections* with an async signal
(embeddings, an LLM) while keeping the structure-aware behaviour for everything else.

Headings and tables still define the structure. Only a section that has to be split anyway
(it exceeds the chunk budget) is handed to `_plan_groups`; small sections stay whole. The
async work happens up front in `achunk`, then the synchronous structure-aware pass consumes
the precomputed plans. Any failure (returns None) falls back to plain fixed chunking.
"""

from __future__ import annotations

from abc import abstractmethod

import structlog

from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.chunkers.fixed_chunker import FixedChunker
from app.domains.ingestion.chunkers.structure_aware_chunker import StructureAwareChunker
from app.domains.ingestion.schemas import ChunkData, ParsedDocument

logger = structlog.get_logger()

Sentence = tuple[str, int | None]  # (text, page)


def pack_groups(
    groups: list[list[str]], chunk_size: int, count_tokens, *, min_fill: float = 0.3
) -> list[list[str]]:
    """Enforce the token budget on proposed groups: split any group that is too big
    (sentence-greedy) and merge neighbouring tiny groups that fit together."""
    split: list[list[str]] = []
    for group in groups:
        current: list[str] = []
        tokens = 0
        for sentence in group:
            t = count_tokens(sentence)
            if current and tokens + t > chunk_size:
                split.append(current)
                current, tokens = [], 0
            current.append(sentence)
            tokens += t
        if current:
            split.append(current)

    merged: list[list[str]] = []
    for group in split:
        if merged:
            prev_tokens = sum(count_tokens(s) for s in merged[-1])
            this_tokens = sum(count_tokens(s) for s in group)
            small = min(prev_tokens, this_tokens) < chunk_size * min_fill
            if small and prev_tokens + this_tokens <= chunk_size:
                merged[-1] = merged[-1] + group
                continue
        merged.append(list(group))
    return merged


class _PlanFallback(BaseChunker):
    """Stands in for the structure-aware chunker's fixed-chunking fallback: uses the
    precomputed plan for a section when there is one, plain fixed chunking otherwise."""

    def __init__(self, owner: PlannedChunker) -> None:
        self._owner = owner
        self._fixed = FixedChunker()

    def chunk(self, parsed: ParsedDocument, chunk_size: int, chunk_overlap: int):
        key = self._owner.plan_key(parsed.pages[0].elements)
        groups = self._owner.plans.get(key)
        if not groups:
            return self._fixed.chunk(parsed, chunk_size, chunk_overlap)
        page = parsed.pages[0].page_number
        return [
            ChunkData(
                content=" ".join(g),
                chunk_index=i,
                token_count=self.count_tokens(" ".join(g)),
                metadata={"page_number": page, self._owner.marker: True},
            )
            for i, g in enumerate(groups)
        ]


class PlannedChunker(StructureAwareChunker):
    marker = "planned_split"  # metadata flag set on chunks split by the plan

    def __init__(self) -> None:
        super().__init__()
        self.plans: dict[tuple[int, ...], list[list[str]]] = {}
        self._fallback = _PlanFallback(self)

    @staticmethod
    def plan_key(elements) -> tuple[int, ...]:
        return tuple(id(e) for e in elements)

    @abstractmethod
    async def _plan_groups(self, sentences: list[str]) -> list[list[str]] | None:
        """Group the sentences of one oversized section. None = use fixed chunking."""

    async def achunk(
        self, parsed: ParsedDocument, chunk_size: int, chunk_overlap: int
    ) -> list[ChunkData]:
        self.plans = {}
        for hierarchy, elements, _page in [
            (h, run, p)
            for h, els, pg in self._group_by_headings(parsed)
            for run, p in self._split_runs(els, pg)
        ]:
            if len(elements) == 1 and elements[0].type == "table":
                continue
            body = "\n\n".join(el.content for el in elements if el.type != "heading").strip()
            if not body:
                continue
            prefix = self._format_hierarchy(hierarchy)
            full = f"{prefix}\n\n{body}" if prefix else body
            if self.count_tokens(full) <= chunk_size:
                continue  # fits: structure-aware keeps it whole

            sentences = [s for el in elements for s in self.split_sentences(el.content)]
            try:
                groups = await self._plan_groups(sentences) if len(sentences) > 2 else None
            except Exception as e:  # planning is an enhancement; never fail ingestion
                logger.warning("chunk_planning_failed", chunker=self.marker, error=str(e))
                groups = None
            if groups:
                self.plans[self.plan_key(elements)] = pack_groups(
                    groups, chunk_size, self.count_tokens
                )
        try:
            return self.chunk(parsed, chunk_size, chunk_overlap)
        finally:
            self.plans = {}
