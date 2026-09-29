import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.rag.schemas import RAGRequest
from app.domains.rag.service import RAGService
from app.domains.retrieval.schemas import RetrievalResult, RetrievedChunk


def make_chunk(content: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
    )


@pytest.mark.asyncio
async def test_rag_query_abstains_when_no_evidence_retrieved():
    service = RAGService()

    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=AsyncMock(
            return_value=RetrievalResult(
                chunks=[], query="test", strategy="hybrid", total_candidates=0, retrieval_time_ms=1.0
            )
        ),
    ):
        response = await service.query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query="unanswerable question", knowledge_base_ids=[uuid.uuid4()]),
        )

    assert response.abstained is True
    assert response.evidence_gate.pass_gate is False
    assert response.citations == []
    assert response.claim_verifications == []
    assert "sufficient evidence" in response.answer.lower()


@pytest.mark.asyncio
async def test_rag_query_abstains_when_all_chunks_below_threshold():
    service = RAGService()
    weak_chunks = [make_chunk("barely related", 0.05), make_chunk("also weak", 0.02)]

    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=AsyncMock(
            return_value=RetrievalResult(
                chunks=weak_chunks,
                query="test",
                strategy="hybrid",
                total_candidates=2,
                retrieval_time_ms=1.0,
            )
        ),
    ), patch(
        "app.domains.rag.service._reranker.rerank",
        new=AsyncMock(return_value=weak_chunks),
    ):
        response = await service.query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query="obscure question", knowledge_base_ids=[uuid.uuid4()]),
        )

    assert response.abstained is True
    assert response.evidence_gate.pass_gate is False


@pytest.mark.asyncio
async def test_rag_query_never_calls_llm_when_abstaining():
    """Ensures no generation cost is incurred when the evidence gate fails."""
    service = RAGService()

    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=AsyncMock(
            return_value=RetrievalResult(
                chunks=[], query="test", strategy="hybrid", total_candidates=0, retrieval_time_ms=1.0
            )
        ),
    ), patch("app.domains.rag.service.get_llm_provider") as mock_get_llm:
        await service.query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query="test", knowledge_base_ids=[uuid.uuid4()]),
        )
        mock_get_llm.assert_not_called()
