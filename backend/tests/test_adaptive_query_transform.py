"""Adaptive query rewriting and batched query embeddings in the RAG pipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.domains.rag.schemas import RAGRequest
from app.domains.rag.service import RAGService
from app.domains.retrieval.query_transform import QueryPlan, needs_upfront_transform
from app.domains.retrieval.schemas import RetrievalResult
from app.providers.embeddings import query_memo
from tests.test_expansion_loop import FakeLLM, chunk, rerank_passthrough

CLEAR = "Why am I getting Error Code E-14 during preheating?"
RELEVANT = "Error Code E-14 means the preheating sensor variance is too high."
IRRELEVANT = "Our office is closed on public holidays."


@pytest.mark.parametrize(
    ("query", "intent", "history", "upfront"),
    [
        (CLEAR, "lookup", False, False),
        (CLEAR, "lookup", True, False),  # self-contained even inside a conversation
        ("Does it also apply to annual plans?", "lookup", True, True),  # follow-up
        ("Compare the OC-500 and OC-700 warranties", "comparison", False, True),
        ("What is E-14? What is E-15?", "lookup", False, True),  # two questions
        ("What is E-14 and how do I fix it", "lookup", False, True),  # multi-part
        ("refund policy", "lookup", False, True),  # too short / vague
    ],
)
def test_needs_upfront_transform(query, intent, history, upfront):
    assert needs_upfront_transform(query, intent, history) is upfront


@pytest.fixture
def transform_on(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_QUERY_TRANSFORM", True)
    monkeypatch.setattr(settings, "QUERY_TRANSFORM_ADAPTIVE", True)
    monkeypatch.setattr(settings, "ENABLE_RESPONSE_CACHE", False)


async def run(query, by_query, plan, calls, plans):
    """by_query: retrieval results keyed by the searched query text."""

    async def retrieve(db, org_id, request, scope=None):
        calls.append((request.strategy, request.query))
        chunks = by_query.get(request.query, [])
        return RetrievalResult(chunks=chunks, query=request.query, strategy=request.strategy,
                               total_candidates=len(chunks), retrieval_time_ms=1.0)

    async def fake_plan(q, llm, history=None, max_extra=3):
        plans.append(q)
        return plan

    with patch("app.domains.rag.service.retrieval_service.retrieve", new=retrieve), patch(
        "app.domains.rag.service._reranker.rerank", new=rerank_passthrough
    ), patch("app.domains.rag.service.get_llm_provider", return_value=FakeLLM()), patch(
        "app.domains.rag.service._detect_and_resolve_conflicts", new=AsyncMock(return_value=[])
    ), patch("app.domains.rag.service.plan_queries", new=fake_plan), patch(
        "app.domains.rag.service.prefetch_query_embeddings", new=AsyncMock()
    ) as prefetch:
        response = await RAGService().query(
            db=AsyncMock(), org_id=uuid.uuid4(),
            request=RAGRequest(query=query, knowledge_base_ids=[uuid.uuid4()]),
        )
    return response, prefetch


PLAN = QueryPlan(original=CLEAR, rewrite="What causes E-14 when preheating?",
                 variants=["E-14 preheat sensor fault"])


async def test_clear_question_answered_first_pass_skips_rewrite(transform_on):
    calls, plans = [], []
    response, _ = await run(CLEAR, {CLEAR: [chunk(RELEVANT, 0.9)]}, PLAN, calls, plans)
    assert not response.abstained
    assert plans == []  # no rewrite LLM call
    assert [q for _, q in calls] == [CLEAR]


async def test_rewrite_runs_when_first_pass_is_insufficient(transform_on):
    calls, plans = [], []
    by_query = {CLEAR: [chunk(IRRELEVANT, 0.1)],
                "What causes E-14 when preheating?": [chunk(RELEVANT, 0.9)]}
    response, prefetch = await run(CLEAR, by_query, PLAN, calls, plans)
    assert plans == [CLEAR]  # deferred rewrite ran once
    first_strategy = calls[0][0]
    # the variants are searched with the same strategy, before other strategies
    assert calls[1:3] == [(first_strategy, "What causes E-14 when preheating?"),
                          (first_strategy, "E-14 preheat sensor fault")]
    assert "query_rewrite" in response.retrieval_metadata["strategies_tried"]
    assert not response.abstained
    # both batches of query embeddings were prefetched (original, then the variants)
    batches = [c.args[1] for c in prefetch.await_args_list]
    assert batches[-1] == ["What causes E-14 when preheating?", "E-14 preheat sensor fault"]


async def test_follow_up_or_comparison_is_rewritten_up_front(transform_on):
    calls, plans = [], []
    q = "Compare the OC-500 and OC-700 warranties"
    plan = QueryPlan(original=q, sub_queries=["OC-500 warranty", "OC-700 warranty"])
    await run(q, {q: [chunk(RELEVANT, 0.9)]}, plan, calls, plans)
    assert plans == [q]
    assert [x for _, x in calls[:3]] == [q, "OC-500 warranty", "OC-700 warranty"]


async def test_adaptive_off_restores_always_rewrite(transform_on, monkeypatch):
    monkeypatch.setattr(settings, "QUERY_TRANSFORM_ADAPTIVE", False)
    calls, plans = [], []
    await run(CLEAR, {CLEAR: [chunk(RELEVANT, 0.9)]}, PLAN, calls, plans)
    assert plans == [CLEAR]


class CountingEmbedder:
    model_name = "m"

    def __init__(self):
        self.text_calls, self.query_calls = [], []

    async def embed_texts(self, texts):
        self.text_calls.append(list(texts))
        return [[float(len(t))] for t in texts]

    async def embed_query(self, q):
        self.query_calls.append(q)
        return [float(len(q))]


async def test_memo_batches_and_reuses_vectors():
    e = CountingEmbedder()
    with query_memo.query_embedding_memo():
        await query_memo.prefetch(e, ["aa", "bbb", "aa"])
        assert await query_memo.embed_query(e, "aa") == [2.0]
        assert await query_memo.embed_query(e, "bbb") == [3.0]
        assert await query_memo.embed_query(e, "cccc") == [4.0]  # not prefetched: own call
        assert await query_memo.embed_query(e, "cccc") == [4.0]  # memoized now
    assert e.text_calls == [["aa", "bbb"]] and e.query_calls == ["cccc"]


async def test_no_memo_is_exact_passthrough():
    e = CountingEmbedder()
    await query_memo.prefetch(e, ["aa"])  # no active memo: does nothing
    assert await query_memo.embed_query(e, "aa") == [2.0]
    assert e.text_calls == [] and e.query_calls == ["aa"]


async def test_memo_is_per_model_and_prefetch_failure_falls_back():
    e = CountingEmbedder()
    other = CountingEmbedder()
    other.model_name = "other"
    broken = MagicMock(model_name="m")
    broken.embed_texts = AsyncMock(side_effect=RuntimeError("boom"))
    with query_memo.query_embedding_memo():
        await query_memo.prefetch(e, ["aa"])
        await query_memo.embed_query(other, "aa")  # different model: no reuse
        assert other.query_calls == ["aa"]
    with query_memo.query_embedding_memo():
        await query_memo.prefetch(broken, ["zz"])  # swallowed
        assert await query_memo.embed_query(e, "zz") == [2.0]
