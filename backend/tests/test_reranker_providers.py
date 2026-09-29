import json
import uuid

import httpx
import pytest

from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.reranker.cohere_reranker import COHERE_RERANK_URL, CohereReranker
from app.providers.reranker.llm_reranker import LLMReranker
from app.providers.reranker.registry import NoReranker, get_reranker


def chunk(content: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="d",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
        authority_tier="authoritative",
        document_version=3,
    )


def cohere_with(handler) -> CohereReranker:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CohereReranker(api_key="k", client=client)


@pytest.mark.asyncio
async def test_cohere_reorders_by_relevance_and_keeps_document_fields():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.92}, {"index": 0, "relevance_score": 0.1}]},
        )

    rr = cohere_with(handler)
    a, b = chunk("weak match", 0.9), chunk("strong match", 0.2)
    result = await rr.rerank("refund window", [a, b], top_k=2)

    assert [c.content for c in result] == ["strong match", "weak match"]
    assert [c.score for c in result] == [0.92, 0.1]
    assert result[0].authority_tier == "authoritative" and result[0].document_version == 3
    assert seen["url"] == COHERE_RERANK_URL and seen["auth"] == "Bearer k"
    assert seen["body"]["query"] == "refund window"
    assert seen["body"]["documents"] == ["weak match", "strong match"]


@pytest.mark.asyncio
async def test_cohere_respects_top_k_and_scores_unreturned_documents_zero():
    def handler(request):
        return httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.7}]})

    result = await cohere_with(handler).rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_k=2)
    assert len(result) == 2 and result[0].content == "c" and result[1].score == 0.0


@pytest.mark.asyncio
async def test_cohere_failure_falls_back_to_retrieval_order():
    def handler(request):
        return httpx.Response(500, json={"message": "boom"})

    chunks = [chunk("a", 0.9), chunk("b", 0.8), chunk("c", 0.7)]
    result = await cohere_with(handler).rerank("q", chunks, top_k=2)
    assert [c.content for c in result] == ["a", "b"]
    assert [c.score for c in result] == [0.9, 0.8]  # untouched


@pytest.mark.asyncio
async def test_cohere_without_api_key_falls_back_instead_of_raising():
    result = await CohereReranker(api_key="").rerank("q", [chunk("a", 0.4)], top_k=1)
    assert [c.score for c in result] == [0.4]


@pytest.mark.asyncio
async def test_cohere_empty_input():
    assert await CohereReranker(api_key="k").rerank("q", [], top_k=3) == []


def test_registry_selects_provider(monkeypatch):
    from app.config import settings

    assert isinstance(get_reranker("cohere"), CohereReranker)
    assert isinstance(get_reranker("llm"), LLMReranker)
    assert isinstance(get_reranker("none"), NoReranker)
    monkeypatch.setattr(settings, "RERANKER_PROVIDER", "cohere")
    assert isinstance(get_reranker(), CohereReranker)
    with pytest.raises(ValueError, match="RERANKER_PROVIDER"):
        get_reranker("bogus")


@pytest.mark.asyncio
async def test_no_reranker_keeps_order_and_scores():
    chunks = [chunk("a", 0.9), chunk("b", 0.2)]
    assert await NoReranker().rerank("q", chunks, top_k=1) == chunks[:1]


def test_llm_reranker_can_be_built_without_api_keys():
    # Regression for the lazy LLM: constructing must not create a provider client.
    rr = LLMReranker(model="gpt-4o-mini")
    assert rr._llm is None
