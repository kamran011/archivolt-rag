from sqlalchemy import Select, cast, or_
from sqlalchemy.dialects.postgresql import JSONB

from app.domains.retrieval.access import AccessScope, visible_document_clause
from app.domains.retrieval.schemas import RetrievalFilters
from app.models.chunk import Chunk
from app.models.document import AuthorityTier, Document

_AUTHORITY_RANK = {
    AuthorityTier.draft: 0,
    AuthorityTier.standard: 1,
    AuthorityTier.authoritative: 2,
}


def apply_common_filters(
    stmt: Select, filters: RetrievalFilters | None, scope: AccessScope | None = None
) -> Select:
    """Applies metadata, freshness, and authority filters shared across all
    retrieval engines. By default (no filters supplied), only current
    (non-superseded) document versions are searched — this is the freshness
    default: prefer current authoritative evidence unless the caller
    explicitly asks for historical versions too."""
    # Access control comes first and is not caller-controllable: restricted documents the
    # scope cannot see are excluded by the query (fail closed when scope is None).
    stmt = stmt.where(visible_document_clause(scope))

    include_superseded = filters.include_superseded if filters else False
    if not include_superseded:
        stmt = stmt.where(Document.is_current.is_(True))

    if not filters:
        return stmt

    if filters.document_ids:
        stmt = stmt.where(Chunk.document_id.in_(filters.document_ids))
    if filters.file_types:
        stmt = stmt.where(Document.file_type.in_(filters.file_types))
    if filters.date_from:
        stmt = stmt.where(Document.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Document.created_at <= filters.date_to)
    if filters.tags:
        # JSONB containment (@>); the portable JSON type's generic contains() is a LIKE.
        tags_col = cast(Document.tags, JSONB)
        stmt = stmt.where(or_(*[tags_col.contains([t]) for t in filters.tags]))
    if filters.effective_from:
        stmt = stmt.where(Document.effective_date >= filters.effective_from)
    if filters.effective_to:
        stmt = stmt.where(Document.effective_date <= filters.effective_to)
    if filters.as_of:
        # Historical question: documents in force on that date (effective on/before it).
        stmt = stmt.where(
            or_(Document.effective_date.is_(None), Document.effective_date <= filters.as_of)
        )
    if filters.min_authority:
        min_rank = _AUTHORITY_RANK.get(AuthorityTier(filters.min_authority), 0)
        allowed_tiers = [t for t, rank in _AUTHORITY_RANK.items() if rank >= min_rank]
        stmt = stmt.where(Document.authority_tier.in_(allowed_tiers))

    return stmt
