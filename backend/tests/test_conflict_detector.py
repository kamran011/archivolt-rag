import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.rag.conflict_detector import ConflictDetector
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.llm.base import LLMResponse


def make_chunk(document_id: uuid.UUID | None = None, content: str = "content") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        document_title="Doc",
        content=content,
        score=0.8,
        metadata={},
        retrieval_method="hybrid",
    )


def make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, prompt_tokens=10, completion_tokens=10, model="test", finish_reason="stop"
    )


@pytest.mark.asyncio
async def test_skips_llm_call_when_all_evidence_from_one_document():
    """No cross-document conflict is possible with a single source document —
    must not spend a token on this check."""
    doc_id = uuid.uuid4()
    chunks = [make_chunk(doc_id), make_chunk(doc_id), make_chunk(doc_id)]

    llm = AsyncMock()
    detector = ConflictDetector()
    result = await detector.detect(chunks, llm)

    assert result == []
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_detects_conflict_across_two_documents():
    chunks = [make_chunk(), make_chunk()]
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=make_llm_response(
            '[{"source_a": 1, "source_b": 2, "topic": "refund window", '
            '"claim_a": "30 days", "claim_b": "14 days"}]'
        )
    )

    detector = ConflictDetector()
    result = await detector.detect(chunks, llm)

    assert len(result) == 1
    assert result[0].topic == "refund window"
    assert result[0].source_a == 1
    assert result[0].source_b == 2


@pytest.mark.asyncio
async def test_no_conflict_returns_empty_list():
    chunks = [make_chunk(), make_chunk()]
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=make_llm_response("[]"))

    detector = ConflictDetector()
    result = await detector.detect(chunks, llm)
    assert result == []


@pytest.mark.asyncio
async def test_handles_llm_failure_gracefully():
    chunks = [make_chunk(), make_chunk()]
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("API down"))

    detector = ConflictDetector()
    result = await detector.detect(chunks, llm)
    assert result == []


@pytest.mark.asyncio
async def test_handles_malformed_json_gracefully():
    chunks = [make_chunk(), make_chunk()]
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=make_llm_response("not json"))

    detector = ConflictDetector()
    result = await detector.detect(chunks, llm)
    assert result == []
