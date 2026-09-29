"""CAG (context-augmented generation): answer from the *whole* knowledge base content.

For a small, stable knowledge base, loading everything can beat retrieval: no ranking can
miss a passage. It is only allowed when the admin enabled it for the KB and the content fits
CAG_MAX_TOKENS; a larger KB is not truncated, it is ineligible and the caller falls back to
RAG. What is loaded is exactly what retrieval could return to this caller: same org, same
knowledge bases, current document versions only, same document access rules (restricted
documents the caller cannot see are excluded in the SQL).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.models.chunk import Chunk
from app.models.document import AuthorityTier, Document
from app.models.knowledge_base import KnowledgeBase

_AUTHORITY_SORT = case(
    (Document.authority_tier == AuthorityTier.authoritative, 0),
    (Document.authority_tier == AuthorityTier.standard, 1),
    else_=2,
)


@dataclass
class CagContext:
    eligible: bool
    reason: str | None = None  # why not eligible
    total_tokens: int = 0
    limit: int = 0
    chunks: list[RetrievedChunk] = field(default_factory=list)


async def load_cag_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    kb_ids: list[uuid.UUID],
    scope: AccessScope | None,
    filters: RetrievalFilters | None = None,
    *,
    max_tokens: int | None = None,
    load_text: bool = True,
) -> CagContext:
    limit = max_tokens if max_tokens is not None else settings.CAG_MAX_TOKENS

    kbs = (
        await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.cag_enabled).where(
                KnowledgeBase.organization_id == org_id, KnowledgeBase.id.in_(kb_ids)
            )
        )
    ).all()
    if not kbs or len(kbs) != len(set(kb_ids)):
        return CagContext(False, "knowledge base not found", limit=limit)
    if not all(enabled for _, enabled in kbs):
        return CagContext(False, "CAG is not enabled for this knowledge base", limit=limit)

    base = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.organization_id == org_id, Chunk.knowledge_base_id.in_(kb_ids))
    )
    base = apply_common_filters(base, filters, scope)

    # Size first, in SQL, so an oversized KB never has its text loaded.
    total = (
        await db.execute(select(func.coalesce(func.sum(base.subquery().c.token_count), 0)))
    ).scalar_one()
    if total > limit:
        return CagContext(
            False, f"knowledge base is too large for CAG ({total} > {limit} tokens)",
            total_tokens=int(total), limit=limit,
        )
    if total == 0:
        return CagContext(False, "knowledge base has no content", limit=limit)

    if not load_text:  # eligibility probe only
        return CagContext(True, total_tokens=int(total), limit=limit)

    rows = (
        await db.execute(base.order_by(_AUTHORITY_SORT, Document.title, Document.id, Chunk.chunk_index))
    ).all()
    chunks = [row_to_retrieved_chunk(c, d, 0.0, "cag") for c, d in rows]
    return CagContext(True, total_tokens=int(total), limit=limit, chunks=chunks)
