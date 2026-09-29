"""
Rule-based conflict resolution (master spec section 29): when two sources
disagree, prefer the one that wins on, in order: source authority, current
status, effective date, version, then leave it unresolved (exposed to the
user) if nothing breaks the tie.
"""

from pydantic import BaseModel

from app.domains.retrieval.schemas import RetrievedChunk
from app.models.document import AuthorityTier

_AUTHORITY_RANK = {
    AuthorityTier.draft: 0,
    AuthorityTier.standard: 1,
    AuthorityTier.authoritative: 2,
}


class ConflictResolution(BaseModel):
    resolved: bool
    winning_source_index: int | None = None
    reason: str | None = None


class ConflictResolver:
    @staticmethod
    def resolve(chunk_a: RetrievedChunk, index_a: int, chunk_b: RetrievedChunk, index_b: int) -> ConflictResolution:
        # 1. Source authority
        rank_a = _AUTHORITY_RANK.get(AuthorityTier(chunk_a.authority_tier), 0)
        rank_b = _AUTHORITY_RANK.get(AuthorityTier(chunk_b.authority_tier), 0)
        if rank_a != rank_b:
            winner = index_a if rank_a > rank_b else index_b
            return ConflictResolution(
                resolved=True, winning_source_index=winner, reason="higher source authority"
            )

        # 2. Current status
        if chunk_a.is_current != chunk_b.is_current:
            winner = index_a if chunk_a.is_current else index_b
            return ConflictResolution(
                resolved=True, winning_source_index=winner, reason="current version vs superseded"
            )

        # 3. Effective date (more recent wins)
        if chunk_a.effective_date and chunk_b.effective_date:
            if chunk_a.effective_date != chunk_b.effective_date:
                winner = index_a if chunk_a.effective_date > chunk_b.effective_date else index_b
                return ConflictResolution(
                    resolved=True, winning_source_index=winner, reason="more recent effective date"
                )
        elif chunk_a.effective_date or chunk_b.effective_date:
            # One side has an explicit effective date and the other doesn't —
            # not a reliable enough signal on its own; fall through.
            pass

        # 4. Document version (only meaningful within the same version family,
        # but a higher version number is still a weak positive signal even
        # across unrelated documents that happen to both be versioned)
        if chunk_a.document_version != chunk_b.document_version:
            winner = index_a if chunk_a.document_version > chunk_b.document_version else index_b
            return ConflictResolution(
                resolved=True, winning_source_index=winner, reason="higher document version"
            )

        # Nothing broke the tie — must be exposed rather than silently picked.
        return ConflictResolution(resolved=False)
