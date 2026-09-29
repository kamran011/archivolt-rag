import uuid
from datetime import UTC, datetime, timedelta

from app.domains.rag.conflict_resolver import ConflictResolver
from app.domains.retrieval.schemas import RetrievedChunk


def make_chunk(
    authority_tier: str = "standard",
    is_current: bool = True,
    effective_date=None,
    document_version: int = 1,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content="content",
        score=0.8,
        metadata={},
        retrieval_method="hybrid",
        authority_tier=authority_tier,
        is_current=is_current,
        effective_date=effective_date,
        document_version=document_version,
    )


def test_higher_authority_wins():
    authoritative = make_chunk(authority_tier="authoritative")
    draft = make_chunk(authority_tier="draft")

    result = ConflictResolver.resolve(authoritative, 1, draft, 2)
    assert result.resolved is True
    assert result.winning_source_index == 1
    assert "authority" in result.reason


def test_current_beats_superseded_when_authority_tied():
    current = make_chunk(authority_tier="standard", is_current=True)
    superseded = make_chunk(authority_tier="standard", is_current=False)

    result = ConflictResolver.resolve(current, 1, superseded, 2)
    assert result.resolved is True
    assert result.winning_source_index == 1
    assert "current" in result.reason.lower() or "superseded" in result.reason.lower()


def test_more_recent_effective_date_wins_when_authority_and_status_tied():
    older = make_chunk(effective_date=datetime(2024, 1, 1, tzinfo=UTC))
    newer = make_chunk(effective_date=datetime(2025, 1, 1, tzinfo=UTC))

    result = ConflictResolver.resolve(older, 1, newer, 2)
    assert result.resolved is True
    assert result.winning_source_index == 2
    assert "recent" in result.reason.lower()


def test_higher_version_wins_as_last_tiebreaker():
    v1 = make_chunk(document_version=1)
    v2 = make_chunk(document_version=2)

    result = ConflictResolver.resolve(v1, 1, v2, 2)
    assert result.resolved is True
    assert result.winning_source_index == 2
    assert "version" in result.reason.lower()


def test_completely_tied_sources_remain_unresolved():
    """The critical safety behavior: when nothing breaks the tie, the
    conflict must be exposed, not silently guessed at."""
    a = make_chunk()
    b = make_chunk()

    result = ConflictResolver.resolve(a, 1, b, 2)
    assert result.resolved is False
    assert result.winning_source_index is None


def test_authority_is_checked_before_freshness():
    """Priority order matters: a draft document from today must still lose
    to an authoritative document from a year ago."""
    old_authoritative = make_chunk(
        authority_tier="authoritative", effective_date=datetime(2020, 1, 1, tzinfo=UTC)
    )
    new_draft = make_chunk(
        authority_tier="draft", effective_date=datetime.now(UTC) - timedelta(days=1)
    )

    result = ConflictResolver.resolve(old_authoritative, 1, new_draft, 2)
    assert result.winning_source_index == 1
    assert "authority" in result.reason
