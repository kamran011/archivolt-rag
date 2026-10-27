"""The same question asked twice in one streamed chat is answered from the answer cache the
second time, through the real app and Postgres. A new document version evicts it."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.cache import MemoryCache, set_cache
from app.main import app
from tests.integration.test_traces import ScriptedLLM
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

QUESTION = "Why am I getting Error Code E-14 during preheating?"


class CountingLLM(ScriptedLLM):
    streams = 0

    async def stream(self, messages, temperature=0.1, max_tokens=2048):
        CountingLLM.streams += 1
        async for part in super().stream(messages, temperature, max_tokens):
            yield part


@pytest.fixture
def cached_chat(monkeypatch, env):  # noqa: F811
    maker, _ = env
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda model: CountingLLM())

    async def rerank(query, chunks, top_k=10):
        return [c.model_copy(update={"score": 0.9}) for c in chunks[:top_k]]

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    monkeypatch.setattr("app.domains.chat.router.AsyncSessionLocal", maker)
    monkeypatch.setattr("app.config.settings.ENABLE_RESPONSE_CACHE", True)
    set_cache(MemoryCache())
    CountingLLM.streams = 0
    yield
    set_cache(None)


async def ask_stream(client, h, kb, conversation_id=None):
    payload = {"message": QUESTION, "knowledge_base_ids": [kb], "stream": True}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    r = await client.post("/api/v1/chat/", json=payload, headers=h)
    assert r.status_code == 200, r.text
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert not [e for e in events if e["type"] == "error"], events
    return events


async def test_repeat_question_in_conversation_is_served_from_cache(env, cached_chat):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"cache-{uuid.uuid4().hex[:6]}")
        doc = await upload(
            c, h, kb, "faq.pdf",
            make_pdf({"Errors": "Error Code E-14 means the preheating sensor variance is high."}),
        )

        first = await ask_stream(c, h, kb)
        done1 = first[-1]
        assert done1["type"] == "done" and not done1["abstained"], done1
        assert "cache_hit" not in done1 and CountingLLM.streams == 1

        second = await ask_stream(c, h, kb, done1["conversation_id"])
        done2 = second[-1]
        assert done2.get("cache_hit") is True, done2
        assert CountingLLM.streams == 1  # no second generation
        assert done2["citations"] == done1["citations"]
        answer1 = "".join(e["content"] for e in first if e["type"] == "token")
        assert second[0]["content"] == answer1

        # Conversation history and the trace list record the cached answer too.
        r = await c.get(f"/api/v1/chat/conversations/{done1['conversation_id']}", headers=h)
        assert r.status_code == 200, r.text

        # A new version of the cited document evicts the cached answer.
        files = {"file": ("faq.pdf", make_pdf({"Errors": "E-14 now means a door fault."}),
                          "application/pdf")}
        r = await c.post(f"/api/v1/knowledge-bases/{kb}/documents/{doc}/versions",
                         files=files, headers=h)
        assert r.status_code == 201, r.text
        third = await ask_stream(c, h, kb, done1["conversation_id"])
        assert not third[-1].get("cache_hit"), third[-1]
        assert CountingLLM.streams == 2
