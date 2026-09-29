import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.domains.rag.schemas import AbstentionReason, RAGRequest
from app.domains.rag.service import RAGService
from app.domains.retrieval.schemas import RetrievalResult, RetrievedChunk
from app.providers.llm.base import LLMResponse


def chunk(content, score=0.9, is_current=True) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Policy",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
        is_current=is_current,
    )


class FakeLLM:
    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        prompt = messages[-1]["content"]
        if "fact-checker" in prompt:
            body = json.dumps(
                [{"claim": "c", "status": "supported", "supporting_sources": [1], "confidence": 1}]
            )
        elif "contradict" in prompt:
            body = "[]"
        else:
            body = "Refunds are allowed within 30 days [Source 1]."
        return LLMResponse(
            content=body, prompt_tokens=1, completion_tokens=1, model="f", finish_reason="stop"
        )


def scripted_retrieval(by_strategy: dict[str, list[RetrievedChunk]], calls: list[str]):
    async def retrieve(db, org_id, request):
        calls.append(request.strategy)
        return RetrievalResult(
            chunks=by_strategy.get(request.strategy, []),
            query=request.query,
            strategy=request.strategy,
            total_candidates=len(by_strategy.get(request.strategy, [])),
            retrieval_time_ms=1.0,
        )

    return retrieve


async def rerank_passthrough(query, chunks, top_k=10):
    # Like the real reranker: best score first.
    return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]


async def run(by_strategy, query="What is the refund window for annual plans?"):
    calls: list[str] = []
    with patch(
        "app.domains.rag.service.retrieval_service.retrieve",
        new=scripted_retrieval(by_strategy, calls),
    ), patch("app.domains.rag.service._reranker.rerank", new=rerank_passthrough), patch(
        "app.domains.rag.service.get_llm_provider", return_value=FakeLLM()
    ), patch(
        "app.domains.rag.service._detect_and_resolve_conflicts", new=AsyncMock(return_value=[])
    ):
        response = await RAGService().query(
            db=AsyncMock(),
            org_id=uuid.uuid4(),
            request=RAGRequest(query=query, knowledge_base_ids=[uuid.uuid4()]),
        )
    return response, calls


IRRELEVANT = "Our office is closed on public holidays."
RELEVANT = "Annual plans have a refund window of 30 days."


@pytest.mark.asyncio
async def test_no_expansion_when_first_attempt_is_sufficient():
    response, calls = await run({"hybrid": [chunk(RELEVANT, 0.5)]})
    assert not response.abstained
    assert calls == ["hybrid"]  # did not run every strategy
    assert response.retrieval_metadata["strategies_tried"] == ["hybrid"]


@pytest.mark.asyncio
async def test_insufficient_first_attempt_expands_and_recovers():
    # Default route for this query is hybrid; it finds something off-topic (passes the
    # score gate, fails sufficiency). The tree strategy finds the real answer.
    response, calls = await run({"hybrid": [chunk(IRRELEVANT, 0.5)], "tree": [chunk(RELEVANT, 0.7)]})
    assert not response.abstained, response.answer
    assert calls == ["hybrid", "tree"]
    assert response.retrieval_metadata["strategies_tried"] == ["hybrid", "tree"]
    assert response.retrieval_metadata["sufficiency"]["sufficient"] is True
    assert any("refund window" in c.content for c in response.citations)


@pytest.mark.asyncio
async def test_expansion_is_bounded_and_then_abstains():
    response, calls = await run(
        {"hybrid": [chunk(IRRELEVANT, 0.5)], "tree": [chunk("Parking is free.", 0.5)]}
    )
    assert response.abstained
    assert response.abstention_reason == AbstentionReason.insufficient_evidence
    assert len(calls) <= 1 + settings.MAX_RETRIEVAL_EXPANSIONS
    assert response.citations == []
    assert "refund" in response.answer.lower() or "evidence" in response.answer.lower()


@pytest.mark.asyncio
async def test_expansion_does_not_repeat_a_strategy():
    # A quoted phrase routes to keyword first; the ladder must then try hybrid and tree.
    response, calls = await run({}, query='What does "refund window" mean for annual plans?')
    assert calls[0] == "keyword"
    assert len(calls) == len(set(calls))


@pytest.mark.asyncio
async def test_only_superseded_evidence_for_a_current_question_abstains_as_outdated():
    response, _ = await run(
        {"hybrid": [chunk(RELEVANT, 0.9, is_current=False)]},
        query="What is the current refund window for annual plans?",
    )
    assert response.abstained
    assert response.abstention_reason == AbstentionReason.outdated


@pytest.mark.asyncio
async def test_sufficiency_gate_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_SUFFICIENCY_GATE", False)
    response, calls = await run({"hybrid": [chunk(IRRELEVANT, 0.5)]})
    assert calls == ["hybrid"] and not response.abstained
