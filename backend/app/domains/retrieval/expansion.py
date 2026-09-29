import uuid

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievedChunk
from app.models.chunk import Chunk
from app.models.document import Document

EXPAND_TOP_N = 3
NEIGHBOR_SCORE_FACTOR = 0.9


async def expand_with_neighbors(
    db: AsyncSession,
    org_id: uuid.UUID,
    chunks: list[RetrievedChunk],
    *,
    top_n: int = EXPAND_TOP_N,
    window: int = 1,
) -> list[RetrievedChunk]:
    """Adds the chunks adjacent (same document, chunk_index ± window) to the
    top hits so answers aren't cut off at chunk boundaries. Neighbors are real
    source chunks, scored just below the hit that pulled them in. Always
    org-scoped; superseded documents are excluded by the shared filters."""
    seeds = chunks[:top_n]
    known = {c.chunk_id for c in chunks}

    wanted: set[tuple[uuid.UUID, int]] = set()
    seed_score: dict[tuple[uuid.UUID, int], float] = {}
    for seed in seeds:
        idx = seed.metadata.get("chunk_index")
        if idx is None:
            continue
        for offset in range(-window, window + 1):
            key = (seed.document_id, idx + offset)
            if offset != 0 and idx + offset >= 0:
                wanted.add(key)
                seed_score[key] = max(seed_score.get(key, 0.0), seed.score)

    if not wanted:
        return chunks

    stmt = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.organization_id == org_id,
            tuple_(Chunk.document_id, Chunk.chunk_index).in_(list(wanted)),
        )
    )
    stmt = apply_common_filters(stmt, None)
    rows = (await db.execute(stmt)).all()

    expanded = list(chunks)
    for chunk, doc in rows:
        if chunk.id in known:
            continue
        score = seed_score[(chunk.document_id, chunk.chunk_index)] * NEIGHBOR_SCORE_FACTOR
        expanded.append(row_to_retrieved_chunk(chunk, doc, score, "neighbor"))
        known.add(chunk.id)
    return expanded
