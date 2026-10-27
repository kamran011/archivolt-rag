import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.cache import MemoryCache, safe
from app.core.cached_providers import CachedEmbeddingProvider, CachedReranker
from app.domains.rag import response_cache
from app.domains.rag.schemas import RAGRequest
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.schemas import RetrievedChunk


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.mark.asyncio
async def test_memory_cache_ttl_sets_incr_and_lock():
    clock = Clock()
    c = MemoryCache(clock=clock)
    await c.set("k", "v", ttl=10)
    assert await c.get("k") == "v"
    clock.t = 11
    assert await c.get("k") is None

    await c.sadd("idx", "a")
    await c.sadd("idx", "b")
    await c.set("a", "1")
    await c.set("b", "2")
    assert await c.invalidate_index("idx") == 2
    assert await c.get("a") is None and await c.smembers("idx") == set()

    assert [await c.incr("n", 5) for _ in range(3)] == [1, 2, 3]
    clock.t = 20
    assert await c.incr("n", 5) == 1

    async with c.lock("x") as got:
        assert got
        async with c.lock("x") as again:
            assert not again
    async with c.lock("x") as got:
        assert got


@pytest.mark.asyncio
async def test_memory_cache_lru_bound():
    c = MemoryCache(max_entries=2)
    for k in "abc":
        await c.set(k, k)
    assert await c.get("a") is None and await c.get("c") == "c"


@pytest.mark.asyncio
async def test_safe_swallows_backend_errors():
    async def boom():
        raise ConnectionError("redis down")

    assert await safe(boom(), "fallback") == "fallback"


@pytest.mark.asyncio
async def test_cached_embeddings_only_embed_misses():
    inner = MagicMock(model_name="m", dimensions=2)
    inner.embed_texts = AsyncMock(side_effect=lambda ts: [[float(len(t)), 0.0] for t in ts])
    p = CachedEmbeddingProvider(inner, MemoryCache(), ttl=60)
    assert await p.embed_texts(["aa", "b"]) == [[2.0, 0.0], [1.0, 0.0]]
    assert await p.embed_texts(["aa", "ccc"]) == [[2.0, 0.0], [3.0, 0.0]]
    assert inner.embed_texts.await_args_list[1].args[0] == ["ccc"]


def _chunk(score):
    cid = uuid.uuid4()
    return RetrievedChunk(
        chunk_id=cid, document_id=cid, document_title="t", content="c", score=score,
        metadata={}, retrieval_method="hybrid",
    )


@pytest.mark.asyncio
async def test_cached_reranker_reuses_order_and_scores():
    a, b = _chunk(0.1), _chunk(0.2)
    inner = MagicMock()
    inner.rerank = AsyncMock(return_value=[b.model_copy(update={"score": 0.9}), a])
    r = CachedReranker(inner, MemoryCache(), ttl=60)
    first = await r.rerank("Q  x", [a, b], 2)
    second = await r.rerank("q x", [b, a], 2)
    assert inner.rerank.await_count == 1
    assert [c.chunk_id for c in second] == [c.chunk_id for c in first]
    assert second[0].score == 0.9


def test_response_cache_key_separates_scopes_and_normalizes_query(monkeypatch):
    org, kb = uuid.uuid4(), uuid.uuid4()
    req = RAGRequest(query="What is  the Policy?", knowledge_base_ids=[kb])
    same = RAGRequest(query="what is the policy?", knowledge_base_ids=[kb])
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    k = response_cache.cache_key
    assert k(org, req, AccessScope(u1)) == k(org, same, AccessScope(u1))
    assert k(org, req, AccessScope(u1)) != k(org, req, AccessScope(u2))
    assert k(org, req, AccessScope(u1)) != k(org, req, AccessScope(u1, is_admin=True))


def test_response_cache_cacheability(monkeypatch):
    monkeypatch.setattr(response_cache.settings, "ENABLE_RESPONSE_CACHE", True)
    kb = [uuid.uuid4()]
    assert response_cache.is_cacheable_request(RAGRequest(query="q", knowledge_base_ids=kb))
    for kw in ({"agentic": True}, {"web_search": True}, {"conversation_history": [{"role": "user", "content": "x"}]}):
        assert not response_cache.is_cacheable_request(RAGRequest(query="q", knowledge_base_ids=kb, **kw))
    monkeypatch.setattr(response_cache.settings, "ENABLE_RESPONSE_CACHE", False)
    assert not response_cache.is_cacheable_request(RAGRequest(query="q", knowledge_base_ids=kb))


@pytest.mark.asyncio
async def test_verify_on_hit_rejects_new_version_or_missing_doc():
    org, doc = uuid.uuid4(), uuid.uuid4()
    db = AsyncMock()
    result = MagicMock()
    db.execute.return_value = result
    result.all.return_value = [(doc, 1)]
    assert await response_cache._verify(db, org, AccessScope(None, True), {str(doc): 1})
    result.all.return_value = [(doc, 2)]  # re-versioned
    assert not await response_cache._verify(db, org, AccessScope(None, True), {str(doc): 1})
    result.all.return_value = []  # superseded / deleted / no longer visible
    assert not await response_cache._verify(db, org, AccessScope(None, True), {str(doc): 1})


@pytest.mark.asyncio
async def test_degraded_rerank_is_served_but_not_cached():
    from app.providers.reranker.llm_reranker import LLMReranker

    class BadThenGoodLLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages, temperature=0.1, max_tokens=2048):
            from app.providers.llm.base import LLMResponse

            self.calls += 1
            body = "sorry, I can't" if self.calls <= 2 else '[{"index": 0, "relevance_score": 9}]'
            return LLMResponse(content=body, prompt_tokens=1, completion_tokens=1,
                               model="f", finish_reason="stop")

    a = _chunk(0.55)
    llm = BadThenGoodLLM()
    cached = CachedReranker(LLMReranker(llm=llm), MemoryCache(), ttl=60)

    first = await cached.rerank("q", [a], 1)  # both attempts unparseable -> fallback
    assert first[0].score == 0.55  # original score kept, not 0.0
    second = await cached.rerank("q", [a], 1)  # not served from cache: asks again
    assert second[0].score == 0.9
    third = await cached.rerank("q", [a], 1)  # good result is cached
    assert third[0].score == 0.9 and llm.calls == 3


@pytest.mark.asyncio
async def test_rerank_retries_once_then_succeeds():
    from app.providers.reranker.llm_reranker import LLMReranker

    class FlakyLLM:
        calls = 0

        async def generate(self, messages, temperature=0.1, max_tokens=2048):
            from app.providers.llm.base import LLMResponse

            FlakyLLM.calls += 1
            if FlakyLLM.calls == 1:
                raise RuntimeError("429 rate limited")
            return LLMResponse(content='[{"index": 0, "relevance_score": 8}]', prompt_tokens=1,
                               completion_tokens=1, model="f", finish_reason="stop")

    out = await LLMReranker(llm=FlakyLLM()).rerank("q", [_chunk(0.1)], 1)
    assert out[0].score == 0.8


@pytest.mark.asyncio
async def test_legacy_empty_rerank_entry_is_ignored():
    a = _chunk(0.4)
    cache = MemoryCache()
    inner = MagicMock()
    inner.rerank = AsyncMock(return_value=[a.model_copy(update={"score": 0.8})])
    r = CachedReranker(inner, cache, ttl=60)
    await r.rerank("q", [a], 1)
    for key in list(cache._data):
        await cache.set(key, "[]")  # what an old poisoned entry looks like
    out = await r.rerank("q", [a], 1)
    assert out and out[0].score == 0.8


@pytest.mark.parametrize(
    ("question", "standalone"),
    [
        ("Why am I getting Error Code E-14 during preheating?", True),
        ("What is the refund window for annual plans?", True),
        ("What about the other model?", False),
        ("Does it also apply to annual plans?", False),
        ("and for the EU?", False),
        ("why?", False),
        ("Explain that in more detail please", False),
    ],
)
def test_is_standalone(question, standalone):
    assert response_cache.is_standalone(question) is standalone


def test_standalone_question_in_conversation_is_cacheable(monkeypatch):
    monkeypatch.setattr(response_cache.settings, "ENABLE_RESPONSE_CACHE", True)
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    kb = [uuid.uuid4()]
    ok = RAGRequest(query="Why am I getting Error Code E-14 during preheating?",
                    knowledge_base_ids=kb, conversation_history=history)
    follow_up = RAGRequest(query="Does it happen during baking too?",
                           knowledge_base_ids=kb, conversation_history=history)
    assert response_cache.is_cacheable_request(ok)
    assert not response_cache.is_cacheable_request(follow_up)


def test_stream_roundtrip_rebuilds_response_and_replays_events():
    done = {
        "type": "done",
        "abstained": False,
        "abstention_reason": None,
        "verification_status": "verified",
        "final_answer": None,
        "citations": [{
            "index": 1, "chunk_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()),
            "document_title": "FAQ", "content": "E-14 means...", "relevance_score": 1.0,
        }],
        "claim_verifications": [],
        "conflicts": [],
        "evidence_gate": {"pass_gate": True, "confidence": 1.0, "top_score": 1.0, "chunk_count": 1},
        "trace_stages": {"meta": {"strategy": "semantic"}},
    }
    response = response_cache.response_from_stream("E-14 means a sensor variance [1].", done)
    assert response.answer == "E-14 means a sensor variance [1]." and len(response.citations) == 1
    token, replay = response_cache.stream_events_for(response)
    assert token == {"type": "token", "content": response.answer}
    assert replay["type"] == "done" and replay["cache_hit"] and replay["final_answer"] is None
    assert replay["citations"][0]["document_title"] == "FAQ"
    assert replay["cost_metadata"]["estimated_cost_usd"] == 0.0
    assert response_cache.response_from_stream("x", {"type": "done"}) is None  # unparseable


@pytest.mark.asyncio
async def test_query_stream_serves_second_identical_question_from_cache(monkeypatch):
    from app.domains.rag import service as rag

    monkeypatch.setattr(response_cache.settings, "ENABLE_RESPONSE_CACHE", True)
    store = MemoryCache()
    monkeypatch.setattr(response_cache, "get_cache", lambda: store)
    doc = uuid.uuid4()
    calls = []

    async def fake_uncached(self, db, org_id, request, scope=None, actor=None):
        calls.append(request.query)
        yield {"type": "token", "content": "E-14 means a sensor variance [1]."}
        yield {
            "type": "done", "abstained": False, "abstention_reason": None,
            "verification_status": "verified", "final_answer": None,
            "citations": [{"index": 1, "chunk_id": str(uuid.uuid4()), "document_id": str(doc),
                           "document_title": "FAQ", "content": "...", "relevance_score": 1.0}],
            "claim_verifications": [], "conflicts": [],
            "evidence_gate": {"pass_gate": True, "confidence": 1.0, "top_score": 1.0,
                              "chunk_count": 1},
            "trace_stages": {}, "trace_id": str(uuid.uuid4()),
        }

    monkeypatch.setattr(rag.RAGService, "_query_stream_uncached", fake_uncached)
    db = AsyncMock()
    current = MagicMock()
    current.all.return_value = [(doc, 1)]
    db.execute.return_value = current

    history = [{"role": "user", "content": "hello"}]
    req = RAGRequest(query="Why am I getting Error Code E-14 during preheating?",
                     knowledge_base_ids=[uuid.uuid4()], conversation_history=history)
    org = uuid.uuid4()
    scope = AccessScope(uuid.uuid4())
    first = [e async for e in rag.rag_service.query_stream(db, org, req, scope)]
    second = [e async for e in rag.rag_service.query_stream(db, org, req, scope)]
    assert calls == [req.query]  # the pipeline ran once
    assert second[-1]["cache_hit"] and second[0]["content"] == first[0]["content"]
    assert second[-1]["trace_id"] != first[-1]["trace_id"]
