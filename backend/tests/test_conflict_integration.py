import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.rag.service import _detect_and_resolve_conflicts
from app.domains.retrieval.schemas import RetrievedChunk


def make_chunk(authority_tier: str = "standard") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content="content",
        score=0.8,
        metadata={},
        retrieval_method="hybrid",
        authority_tier=authority_tier,
    )


class FakeDetected:
    def __init__(self, source_a, source_b, topic="topic", claim_a="a", claim_b="b"):
        self.source_a = source_a
        self.source_b = source_b
        self.topic = topic
        self.claim_a = claim_a
        self.claim_b = claim_b


@pytest.mark.asyncio
async def test_ignores_fabricated_source_indices():
    """Same hallucination guard as citations: a detected 'conflict' pointing
    at a source number beyond what was actually supplied must be dropped."""
    chunks = [make_chunk(), make_chunk()]

    with patch(
        "app.domains.rag.service.conflict_detector.detect",
        new=AsyncMock(return_value=[FakeDetected(source_a=1, source_b=99)]),
    ):
        result = await _detect_and_resolve_conflicts(chunks, llm=AsyncMock())

    assert result == []


@pytest.mark.asyncio
async def test_resolves_valid_conflict_using_authority_tiebreak():
    chunks = [make_chunk(authority_tier="authoritative"), make_chunk(authority_tier="draft")]

    with patch(
        "app.domains.rag.service.conflict_detector.detect",
        new=AsyncMock(
            return_value=[FakeDetected(source_a=1, source_b=2, topic="pricing")]
        ),
    ):
        result = await _detect_and_resolve_conflicts(chunks, llm=AsyncMock())

    assert len(result) == 1
    assert result[0].resolved is True
    assert result[0].winning_source == 1
    assert result[0].topic == "pricing"


@pytest.mark.asyncio
async def test_no_detected_conflicts_returns_empty():
    chunks = [make_chunk(), make_chunk()]
    with patch(
        "app.domains.rag.service.conflict_detector.detect", new=AsyncMock(return_value=[])
    ):
        result = await _detect_and_resolve_conflicts(chunks, llm=AsyncMock())
    assert result == []
