import uuid
from datetime import UTC

import pytest

from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.llm.base import LLMResponse
from app.providers.reranker.llm_reranker import LLMReranker


def make_chunk(content: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
    )


class FakeLLM:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content, self.error = content, error

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        if self.error:
            raise self.error
        return LLMResponse(
            content=self.content or "",
            prompt_tokens=1,
            completion_tokens=1,
            model="fake",
            finish_reason="stop",
        )


def make_reranker(content: str | None = None, error: Exception | None = None) -> LLMReranker:
    return LLMReranker(model="gpt-4o-mini", llm=FakeLLM(content, error))


@pytest.mark.asyncio
async def test_reranker_sorts_by_llm_score_descending():
    reranker = make_reranker(
        '[{"index": 0, "relevance_score": 2}, {"index": 1, "relevance_score": 9}]'
    )

    chunks = [make_chunk("low relevance"), make_chunk("high relevance")]
    result = await reranker.rerank("query", chunks, top_k=2)

    assert result[0].content == "high relevance"
    assert result[1].content == "low relevance"


@pytest.mark.asyncio
async def test_reranker_normalizes_scores_to_0_1_range():
    reranker = make_reranker(
        '[{"index": 0, "relevance_score": 10}]'
    )

    result = await reranker.rerank("query", [make_chunk("text")], top_k=1)
    assert result[0].score == 1.0


@pytest.mark.asyncio
async def test_reranker_respects_top_k():
    reranker = make_reranker(
        '[{"index": 0, "relevance_score": 5}, {"index": 1, "relevance_score": 8}, '
            '{"index": 2, "relevance_score": 3}]'
    )

    chunks = [make_chunk("a"), make_chunk("b"), make_chunk("c")]
    result = await reranker.rerank("query", chunks, top_k=2)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_reranker_falls_back_to_original_score_on_api_failure():
    reranker = make_reranker(error=Exception("API down"))

    chunks = [make_chunk("text", score=0.42)]
    result = await reranker.rerank("query", chunks, top_k=1)

    assert len(result) == 1
    assert result[0].score == 0.42


@pytest.mark.asyncio
async def test_reranker_handles_malformed_json_gracefully():
    reranker = make_reranker(
        "not valid json at all"
    )

    chunks = [make_chunk("text")]
    result = await reranker.rerank("query", chunks, top_k=1)

    assert len(result) == 1
    assert result[0].score == 0.0


@pytest.mark.asyncio
async def test_reranker_strips_markdown_code_fences():
    reranker = make_reranker(
        '```json\n[{"index": 0, "relevance_score": 7}]\n```'
    )

    result = await reranker.rerank("query", [make_chunk("text")], top_k=1)
    assert result[0].score == 0.7


@pytest.mark.asyncio
async def test_reranker_empty_input_returns_empty():
    reranker = LLMReranker(model="gpt-4o-mini")
    result = await reranker.rerank("query", [], top_k=5)
    assert result == []


@pytest.mark.asyncio
async def test_reranker_preserves_authority_and_version_fields():
    """Regression: reranking must not drop document-level fields, or conflict
    resolution (authority/freshness/version) silently sees defaults."""
    from datetime import datetime

    reranker = make_reranker(
        '[{"index": 0, "relevance_score": 8}]'
    )
    when = datetime(2025, 1, 1, tzinfo=UTC)
    chunk = make_chunk("policy text").model_copy(
        update={
            "authority_tier": "authoritative",
            "is_current": False,
            "document_version": 4,
            "effective_date": when,
        }
    )

    [result] = await reranker.rerank("query", [chunk], top_k=1)

    assert result.authority_tier == "authoritative"
    assert result.is_current is False
    assert result.document_version == 4
    assert result.effective_date == when
    assert result.score == 0.8
