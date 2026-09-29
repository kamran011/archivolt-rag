"""Answer-mode dispatch (rag / cag / hybrid) with a scripted loader and retrieval."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.domains.rag.schemas import RAGRequest
from app.domains.rag.service import RAGService
from app.domains.retrieval.cag import CagContext
from app.domains.retrieval.schemas import RetrievalResult, RetrievedChunk
from app.providers.llm.base import LLMResponse


def chunk(text, doc=None, title="Handbook", score=0.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=doc or uuid.uuid4(), document_title=title,
        content=text, score=score, metadata={}, retrieval_method="cag",
    )


class LLM:
    def __init__(self):
        self.prompts = []

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        self.prompts.append("\n".join(m["content"] for m in messages))
        last = messages[-1]["content"]
        if "fact-checker" in last:
            body = json.dumps([{"claim": "c", "status": "supported", "supporting_sources": [1],
                                "confidence": 1}])
        elif "contradict" in last:
            body = "[]"
        else:
            body = "Answer from the sources [Source 1]."
        return LLMResponse(content=body, prompt_tokens=1, completion_tokens=1, model="f",
                           finish_reason="stop")


FULL_KB = [
    chunk("Annual plans have a refund period of thirty days."),
    chunk("Shipping takes five business days by carrier."),
    chunk("Support hours are nine to five on weekdays."),
]


async def run(mode, *, cag: CagContext, rag_chunks=(), rag_score=0.9,
              query="What is the refund period for annual plans?"):
    llm = LLM()
    calls = {"retrieve": 0, "cag": 0}

    async def retrieve(db, org_id, request, embedding_model="x", scope=None):
        calls["retrieve"] += 1
        return RetrievalResult(chunks=[c.model_copy(update={"score": rag_score}) for c in rag_chunks],
                               query=request.query, strategy=request.strategy,
                               total_candidates=len(rag_chunks), retrieval_time_ms=1.0)

    async def load(*args, **kwargs):
        calls["cag"] += 1
        return cag

    async def rerank(q, chunks, top_k=10):
        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]

    with patch("app.domains.rag.service.retrieval_service.retrieve", new=retrieve), patch(
        "app.domains.rag.service.load_cag_context", new=load
    ), patch("app.domains.rag.service._reranker.rerank", new=rerank), patch(
        "app.domains.rag.service.get_llm_provider", return_value=llm
    ), patch("app.domains.rag.service._detect_and_resolve_conflicts",
             new=AsyncMock(return_value=[])):
        response = await RAGService().query(
            db=AsyncMock(), org_id=uuid.uuid4(),
            request=RAGRequest(query=query, knowledge_base_ids=[uuid.uuid4()], mode=mode),
        )
    return response, llm, calls


def eligible(chunks=FULL_KB, tokens=100):
    return CagContext(True, total_tokens=tokens, limit=12000, chunks=list(chunks))


def ineligible(reason="CAG is not enabled for this knowledge base"):
    return CagContext(False, reason, limit=12000)


@pytest.mark.asyncio
async def test_rag_mode_never_touches_cag():
    _, _, calls = await run("rag", cag=eligible(), rag_chunks=[FULL_KB[0]])
    assert calls == {"retrieve": 1, "cag": 0}


@pytest.mark.asyncio
async def test_cag_mode_sends_the_whole_kb_and_skips_retrieval():
    response, llm, calls = await run("cag", cag=eligible())
    assert calls == {"retrieve": 0, "cag": 1}
    assert not response.abstained
    prompt = llm.prompts[0]
    for c in FULL_KB:
        assert c.content in prompt  # everything is in context, nothing ranked away
    md = response.retrieval_metadata
    assert md["answer_mode"] == "cag" and md["strategy"] == "cag"
    assert md["chunks_in_context"] == 3 and md["strategies_tried"] == ["cag"]
    [citation] = response.citations
    assert "refund period" in citation.content  # Source 1 is the most relevant (best term overlap)


@pytest.mark.asyncio
async def test_cag_orders_context_by_relevance_so_the_best_passage_is_source_1():
    _, llm, _ = await run("cag", cag=eligible([FULL_KB[2], FULL_KB[1], FULL_KB[0]]))
    system = llm.prompts[0]
    assert system.index("refund period") < system.index("Shipping takes")


@pytest.mark.asyncio
async def test_cag_still_abstains_when_the_kb_does_not_cover_the_question():
    response, _, _ = await run(
        "cag", cag=eligible(), query="What is the airspeed velocity of an unladen swallow?"
    )
    assert response.abstained and response.citations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "CAG is not enabled for this knowledge base",
        "knowledge base is too large for CAG (99999 > 12000 tokens)",
        "knowledge base has no content",
    ],
)
async def test_ineligible_kb_falls_back_to_rag_and_says_why(reason):
    response, _, calls = await run("cag", cag=ineligible(reason), rag_chunks=[FULL_KB[0]])
    assert calls == {"retrieve": 1, "cag": 1} and not response.abstained
    md = response.retrieval_metadata
    assert md["answer_mode"] == "rag" and md["cag_note"] == reason


@pytest.mark.asyncio
async def test_hybrid_uses_rag_when_it_is_sufficient_and_never_loads_cag():
    response, _, calls = await run("hybrid", cag=eligible(), rag_chunks=[FULL_KB[0]])
    assert calls == {"retrieve": 1, "cag": 0}
    assert response.retrieval_metadata["answer_mode"] == "rag"


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_cag_when_rag_is_insufficient():
    # RAG only finds an unrelated, low-scoring passage; the full KB does cover the question.
    response, llm, calls = await run(
        "hybrid", cag=eligible(), rag_chunks=[chunk("Parking is free.", score=0.4)], rag_score=0.4
    )
    assert calls["retrieve"] >= 1 and calls["cag"] == 1
    assert not response.abstained
    md = response.retrieval_metadata
    assert md["answer_mode"] == "cag" and md["strategies_tried"][-1] == "cag"
    assert "refund period" in llm.prompts[0]


@pytest.mark.asyncio
async def test_hybrid_abstains_with_a_note_when_neither_covers_the_question():
    response, _, _ = await run(
        "hybrid", cag=eligible(), rag_chunks=[chunk("Parking is free.", score=0.4)], rag_score=0.4,
        query="What is the airspeed velocity of an unladen swallow?",
    )
    assert response.abstained


@pytest.mark.asyncio
async def test_hybrid_with_ineligible_kb_reports_the_reason():
    response, _, _ = await run(
        "hybrid", cag=ineligible("knowledge base is too large for CAG (99999 > 12000 tokens)"),
        rag_chunks=[chunk("Parking is free.", score=0.4)], rag_score=0.4,
    )
    assert response.abstained
    assert "too large" in response.retrieval_metadata["cag_note"]


def test_cag_budget_is_configurable():
    assert settings.CAG_MAX_TOKENS > settings.MAX_CONTEXT_TOKENS
