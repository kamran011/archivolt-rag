from sqlalchemy import Select

from app.domains.retrieval.schemas import RetrievalFilters
from app.models.chunk import Chunk
from app.models.document import AuthorityTier, Document

_AUTHORITY_RANK = {
    AuthorityTier.draft: 0,
    AuthorityTier.standard: 1,
    AuthorityTier.authoritative: 2,
}


def apply_common_filters(stmt: Select, filters: RetrievalFilters | None) -> Select:
    """Applies metadata, freshness, and authority filters shared across all
    retrieval engines. By default (no filters supplied), only current
    (non-superseded) document versions are searched — this is the freshness
    default: prefer current authoritative evidence unless the caller
    explicitly asks for historical versions too."""
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
    if filters.min_authority:
        min_rank = _AUTHORITY_RANK.get(AuthorityTier(filters.min_authority), 0)
        allowed_tiers = [t for t, rank in _AUTHORITY_RANK.items() if rank >= min_rank]
        stmt = stmt.where(Document.authority_tier.in_(allowed_tiers))

    return stmt
