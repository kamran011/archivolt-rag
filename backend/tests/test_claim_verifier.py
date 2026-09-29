import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.rag.claim_verifier import ClaimVerifier
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.llm.base import LLMResponse


def make_chunk(content: str = "evidence") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
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
async def test_verify_claims_parses_supported_and_unsupported():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=make_llm_response(
            '[{"claim": "X is true", "supported": true, "supporting_sources": [1], "confidence": 0.9}, '
            '{"claim": "Y is false", "supported": false, "supporting_sources": [], "confidence": 0.7}]'
        )
    )

    verifier = ClaimVerifier()
    result = await verifier.verify_claims("some answer", [make_chunk()], llm)

    assert len(result) == 2
    assert result[0].supported is True
    assert result[1].supported is False


@pytest.mark.asyncio
async def test_verify_claims_returns_empty_on_empty_chunks():
    llm = AsyncMock()
    verifier = ClaimVerifier()
    result = await verifier.verify_claims("answer", [], llm)
    assert result == []
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_verify_claims_returns_empty_on_empty_answer():
    llm = AsyncMock()
    verifier = ClaimVerifier()
    result = await verifier.verify_claims("", [make_chunk()], llm)
    assert result == []


@pytest.mark.asyncio
async def test_verify_claims_handles_llm_failure_gracefully():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("API error"))

    verifier = ClaimVerifier()
    result = await verifier.verify_claims("answer", [make_chunk()], llm)
    assert result == []


@pytest.mark.asyncio
async def test_verify_claims_handles_malformed_json():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=make_llm_response("not json"))

    verifier = ClaimVerifier()
    result = await verifier.verify_claims("answer", [make_chunk()], llm)
    assert result == []


@pytest.mark.asyncio
async def test_verify_claims_strips_markdown_fences():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=make_llm_response(
            '```json\n[{"claim": "X", "supported": true, "supporting_sources": [1], "confidence": 0.8}]\n```'
        )
    )

    verifier = ClaimVerifier()
    result = await verifier.verify_claims("answer", [make_chunk()], llm)
    assert len(result) == 1
    assert result[0].claim == "X"
