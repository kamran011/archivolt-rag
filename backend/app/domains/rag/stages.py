"""Per-stage evidence snapshots for persisted traces.

Records ids, scores and *why* candidates dropped out at each stage — not chunk text —
so a developer can reconstruct why an answer used the evidence it did.
"""

import uuid
from collections.abc import Iterable

from app.domains.retrieval.schemas import RetrievedChunk

REASON_BELOW_MIN_SCORE = "below_min_score"
REASON_NEAR_DUPLICATE = "near_duplicate"
REASON_CONTEXT_BUDGET = "context_budget"
REASON_NOT_RERANKED = "not_reranked"


def brief(chunks: Iterable[RetrievedChunk]) -> list[dict]:
    return [
        {
            "chunk_id": str(c.chunk_id),
            "document_id": str(c.document_id),
            "title": c.document_title,
            "score": round(c.score, 4),
            "method": c.retrieval_method,
            "page": c.metadata.get("page_number") if isinstance(c.metadata, dict) else None,
        }
        for c in chunks
    ]


def excluded(
    before: Iterable[RetrievedChunk], after: Iterable[RetrievedChunk], stage: str, reason: str
) -> list[dict]:
    """Chunks present in `before` but not `after`, tagged with the stage and reason."""
    kept = {c.chunk_id for c in after}
    return [
        {**b, "stage": stage, "reason": reason} for b in brief(c for c in before if c.chunk_id not in kept)
    ]


def build_stages(
    *,
    candidates: list[RetrievedChunk],
    reranked: list[RetrievedChunk],
    after_score: list[RetrievedChunk],
    filtered: list[RetrievedChunk],
    selected: list[RetrievedChunk],
    cited_chunk_ids: Iterable[uuid.UUID],
    filter_drops: Iterable[tuple[RetrievedChunk, str, str]] | None = None,
) -> dict:
    """`filter_drops` (from EvidenceFilter.run_pipeline) attributes each post-score drop to
    its own stage and reason; without it they are all reported as near-duplicates."""
    if filter_drops is None:
        between = excluded(after_score, filtered, "dedupe", REASON_NEAR_DUPLICATE)
    else:
        between = [
            {**b, "stage": stage, "reason": reason}
            for chunk, stage, reason in filter_drops
            for b in brief([chunk])
        ]
    excl = (
        excluded(candidates, reranked, "rerank", REASON_NOT_RERANKED)
        + excluded(reranked, after_score, "score_filter", REASON_BELOW_MIN_SCORE)
        + between
        + excluded(filtered, selected, "context", REASON_CONTEXT_BUDGET)
    )
    return {
        "retrieved": brief(candidates),
        "reranked": brief(reranked),
        "filtered": brief(filtered),
        "selected": brief(selected),
        "cited": [str(i) for i in cited_chunk_ids],
        "excluded": excl,
    }
