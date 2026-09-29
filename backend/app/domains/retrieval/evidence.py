from dataclasses import dataclass, field

import tiktoken

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk

_encoding = tiktoken.get_encoding("cl100k_base")


_AUTHORITY_ORDER = {"draft": 0, "standard": 1, "authoritative": 2}

REASON_SUPERSEDED = "superseded_version"
REASON_LOW_AUTHORITY = "lower_authority_than_available"
REASON_NEAR_DUPLICATE = "near_duplicate"
REASON_DOCUMENT_CAP = "document_cap"


@dataclass
class FilterOutcome:
    kept: list[RetrievedChunk]
    # (chunk, stage, reason) for everything the pipeline removed after the score filter.
    dropped: list[tuple[RetrievedChunk, str, str]] = field(default_factory=list)


class EvidenceFilter:
    @staticmethod
    def remove_superseded(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Drop superseded versions when current evidence is available. If there is no
        current evidence at all, keep them (the sufficiency gate then reports 'outdated')."""
        if not any(c.is_current for c in chunks):
            return chunks
        return [c for c in chunks if c.is_current]

    @staticmethod
    def remove_low_authority(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Drop draft/unreviewed evidence whenever reviewed (standard/authoritative)
        evidence is present. Drafts are kept when they are all there is."""
        if not any(_AUTHORITY_ORDER.get(c.authority_tier, 1) > 0 for c in chunks):
            return chunks
        return [c for c in chunks if _AUTHORITY_ORDER.get(c.authority_tier, 1) > 0]

    @staticmethod
    def limit_per_document(
        chunks: list[RetrievedChunk], max_per_document: int
    ) -> list[RetrievedChunk]:
        """Keep the best `max_per_document` chunks per document (input is best-first), so
        one long document cannot crowd out other sources."""
        counts: dict = {}
        kept = []
        for c in chunks:
            counts[c.document_id] = counts.get(c.document_id, 0) + 1
            if counts[c.document_id] <= max_per_document:
                kept.append(c)
        return kept

    @classmethod
    def run_pipeline(
        cls,
        reranked: list[RetrievedChunk],
        *,
        keep_superseded: bool = False,
        max_per_document: int | None = None,
    ) -> tuple[list[RetrievedChunk], FilterOutcome]:
        """score -> superseded -> authority -> near-duplicate -> per-document cap.
        Returns (chunks after the score filter, outcome with the final kept list and every
        later drop labelled with its stage and reason)."""
        after_score = cls.filter_by_score(reranked)
        dropped: list[tuple[RetrievedChunk, str, str]] = []
        current = after_score

        def step(name: str, reason: str, fn) -> None:
            nonlocal current
            result = fn(current)
            kept_ids = {c.chunk_id for c in result}
            dropped.extend((c, name, reason) for c in current if c.chunk_id not in kept_ids)
            current = result

        if not keep_superseded:
            step("stale", REASON_SUPERSEDED, cls.remove_superseded)
        step("authority", REASON_LOW_AUTHORITY, cls.remove_low_authority)
        step("dedupe", REASON_NEAR_DUPLICATE, cls.deduplicate)
        cap = max_per_document if max_per_document is not None else settings.MAX_CHUNKS_PER_DOCUMENT
        if cap and cap > 0:
            step("diversity", REASON_DOCUMENT_CAP, lambda cs: cls.limit_per_document(cs, cap))
        return after_score, FilterOutcome(kept=current, dropped=dropped)

    @staticmethod
    def filter_by_score(
        chunks: list[RetrievedChunk],
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        threshold = min_score if min_score is not None else settings.SCORE_FILTER_THRESHOLD
        return [c for c in chunks if c.score >= threshold]

    @staticmethod
    def deduplicate(
        chunks: list[RetrievedChunk],
        similarity_threshold: float = 0.9,
    ) -> list[RetrievedChunk]:
        """Removes near-duplicate chunks using Jaccard similarity over token sets.
        Chunks are processed in input order (assumed pre-sorted by relevance),
        so the higher-ranked chunk of any near-duplicate pair is kept."""
        kept: list[RetrievedChunk] = []
        kept_token_sets: list[set[str]] = []

        for chunk in chunks:
            tokens = set(chunk.content.lower().split())
            is_duplicate = False
            for existing_tokens in kept_token_sets:
                if _jaccard_similarity(tokens, existing_tokens) >= similarity_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(chunk)
                kept_token_sets.append(tokens)

        return kept


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


class ContextAssembler:
    @staticmethod
    def assemble(
        chunks: list[RetrievedChunk],
        max_tokens: int | None = None,
    ) -> tuple[list[RetrievedChunk], int]:
        """Greedily packs chunks (assumed pre-sorted by descending relevance)
        into a token budget. Returns the selected chunks and total token count."""
        budget = max_tokens if max_tokens is not None else settings.MAX_CONTEXT_TOKENS
        selected: list[RetrievedChunk] = []
        total_tokens = 0

        for chunk in chunks:
            chunk_tokens = len(_encoding.encode(chunk.content))
            if total_tokens + chunk_tokens > budget:
                continue  # skip chunks that don't fit rather than truncating mid-content
            selected.append(chunk)
            total_tokens += chunk_tokens

        return selected, total_tokens

    @staticmethod
    def format_with_citations(chunks: list[RetrievedChunk]) -> str:
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            page = chunk.metadata.get("page_number")
            location = f", p.{page}" if page else ""
            parts.append(f"[Source {i} - {chunk.document_title}{location}]:\n{chunk.content}")
        return "\n\n".join(parts)
