"""Reciprocal Rank Fusion — combines multiple ranked result lists into one."""

from app.domains.retrieval.schemas import RetrievedChunk

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievedChunk]],
    k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    """
    Fuses multiple ranked chunk lists using RRF: score = sum(1 / (k + rank))
    across all lists a chunk appears in (rank is 1-indexed). Chunks appearing
    in more lists, or ranked higher within a list, score higher.
    """
    scores: dict[str, float] = {}
    chunks_by_id: dict[str, RetrievedChunk] = {}
    methods_by_id: dict[str, set[str]] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list, start=1):
            key = str(chunk.chunk_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            chunks_by_id[key] = chunk
            methods_by_id.setdefault(key, set()).add(chunk.retrieval_method)

    fused: list[RetrievedChunk] = []
    for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        original = chunks_by_id[key]
        methods = methods_by_id[key]
        fused.append(
            original.model_copy(
                update={
                    "score": score,
                    "retrieval_method": "hybrid" if len(methods) > 1 else next(iter(methods)),
                }
            )
        )

    return fused
