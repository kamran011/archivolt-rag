"""Chat -> persisted trace + usage ledger, through the real app and Postgres.
The LLM and reranker are scripted (no API keys); retrieval, persistence, RBAC are real."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models.rag_trace import RagTrace, UsageLedger
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    token,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

ANSWER = "Annual plans can be refunded within 30 days [Source 1]."


class ScriptedLLM:
    """Routes on prompt content: verifier, conflict check, or answer generation."""

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        from app.providers.llm.base import LLMResponse

        prompt = messages[-1]["content"]
        if "fact-checker" in prompt:
            body = json.dumps(
                [
                    {
                        "claim": "Annual plans can be refunded within 30 days",
                        "status": "supported",
                        "supporting_sources": [1],
                        "confidence": 0.95,
                    }
                ]
            )
        elif "contradict" in prompt:
            body = "[]"
        else:
            body = ANSWER
        return LLMResponse(
            content=body, prompt_tokens=120, completion_tokens=20, model="fake", finish_reason="stop"
        )

    async def stream(self, messages, temperature=0.1, max_tokens=2048):
        for part in ANSWER.split(" "):
            yield part + " "


@pytest.fixture
def scripted(monkeypatch, env):  # noqa: F811
    maker, _ = env
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda model: ScriptedLLM())

    async def rerank(query, chunks, top_k=10):
        return [c.model_copy(update={"score": 0.9}) for c in chunks[:top_k]]

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    # The streaming endpoint opens its own session; point it at the test database.
    monkeypatch.setattr("app.domains.chat.router.AsyncSessionLocal", maker)


async def ask(client, h, kb, message, stream=False):
    return await client.post(
        "/api/v1/chat/",
        json={"message": message, "knowledge_base_ids": [kb], "stream": stream},
        headers=h,
    )


async def test_chat_persists_trace_ledger_and_enforces_access(env, scripted):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"trace-{uuid.uuid4().hex[:6]}")
        await upload(
            c, h, kb, "policy.pdf",
            make_pdf({"Refunds": "Annual plans can be refunded within 30 days of purchase."}),
        )

        r = await ask(c, h, kb, "What is the refund window for annual plans?")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["abstained"] is False and body["citations"], body
        assert body["verification_status"] == "verified"
        assert "trace_stages" not in body  # internal, never sent to clients
        trace_id = body["retrieval_metadata"]["trace_id"]

        # Trace is retrievable by an admin and shows what happened at each stage.
        r = await c.get(f"/api/v1/observability/traces/{trace_id}", headers=h)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["abstained"] is False and t["query"].startswith("What is the refund")
        assert t["stages"]["retrieved"] and t["stages"]["selected"]
        cited_id = body["citations"][0]["chunk_id"]
        assert cited_id in t["stages"]["cited"]
        assert t["spans"] and t["total_ms"] is not None

        r = await c.get("/api/v1/observability/traces", headers=h)
        assert [x["id"] for x in r.json()] == [trace_id]

        # Usage ledger row references the trace.
        async with maker() as s:
            rows = (
                await s.execute(select(UsageLedger).where(UsageLedger.trace_id == uuid.UUID(trace_id)))
            ).scalars().all()
            assert len(rows) == 1 and rows[0].kind == "llm"
            assert rows[0].input_tokens == 120 and rows[0].output_tokens == 20

        # A plain member cannot read traces (they contain other users' questions).
        member = uuid.uuid4()
        org = h["X-Organization-Id"]
        r = await c.post(
            f"/api/v1/organizations/{org}/members",
            json={"user_id": str(member), "role": "member"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        h_member = {**token(member), "X-Organization-Id": org}
        assert (await c.get("/api/v1/observability/traces", headers=h_member)).status_code == 403

        # Another org's admin sees 404 for this trace id, and an empty list.
        h_other, _ = await onboard(c, orgs, uuid.uuid4(), f"other-{uuid.uuid4().hex[:6]}")
        assert (
            await c.get(f"/api/v1/observability/traces/{trace_id}", headers=h_other)
        ).status_code == 404
        assert (await c.get("/api/v1/observability/traces", headers=h_other)).json() == []


async def test_abstention_is_traced_with_reason(env, scripted):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"abst-{uuid.uuid4().hex[:6]}")  # empty KB
        r = await ask(c, h, kb, "What is the refund window?")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["abstained"] is True
        assert body["abstention_reason"] == "insufficient_evidence"

        r = await c.get(
            "/api/v1/observability/traces", params={"abstained": True}, headers=h
        )
        traces = r.json()
        assert len(traces) == 1
        assert traces[0]["abstention_reason"] == "insufficient_evidence"


async def test_streaming_chat_persists_trace_without_leaking_stages(env, scripted):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"strm-{uuid.uuid4().hex[:6]}")
        await upload(
            c, h, kb, "policy.pdf",
            make_pdf({"Refunds": "Annual plans can be refunded within 30 days of purchase."}),
        )
        r = await ask(c, h, kb, "What is the refund window for annual plans?", stream=True)
        assert r.status_code == 200
        events = [
            json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")
        ]
        done = next(e for e in events if e["type"] == "done")
        assert "trace_stages" not in done
        assert done["abstained"] is False and done["citations"]

        r = await c.get(f"/api/v1/observability/traces/{done['trace_id']}", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["stages"]["selected"]


async def test_trace_row_persisted_in_db(env, scripted):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"db-{uuid.uuid4().hex[:6]}")
        r = await ask(c, h, kb, "anything?")
        trace_id = uuid.UUID(r.json()["retrieval_metadata"]["trace_id"])
    async with maker() as s:
        row = (await s.execute(select(RagTrace).where(RagTrace.id == trace_id))).scalar_one()
        assert row.abstained is True and row.organization_id == uuid.UUID(h["X-Organization-Id"])


async def test_conversations_are_private_to_their_author(env, scripted):  # noqa: F811
    """Two members of the same org: one must not read, continue or delete the other's
    conversation (prior messages are fed to the LLM, so continuing it would leak them)."""
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h_alice, kb = await onboard(c, orgs, uuid.uuid4(), f"conv-{uuid.uuid4().hex[:6]}")
        org = h_alice["X-Organization-Id"]
        await upload(
            c, h_alice, kb, "policy.pdf",
            make_pdf({"Refunds": "Annual plans can be refunded within 30 days of purchase."}),
        )
        bob = uuid.uuid4()
        r = await c.post(
            f"/api/v1/organizations/{org}/members",
            json={"user_id": str(bob), "role": "member"},
            headers=h_alice,
        )
        assert r.status_code == 201, r.text
        h_bob = {**token(bob), "X-Organization-Id": org}

        r = await ask(c, h_alice, kb, "What is the refund window for annual plans?")
        assert r.status_code == 200, r.text
        listing = await c.get("/api/v1/chat/conversations", headers=h_alice)
        conv_id = listing.json()[0]["id"]

        # Author can read her conversation (messages are loaded explicitly, not lazily).
        r = await c.get(f"/api/v1/chat/conversations/{conv_id}", headers=h_alice)
        assert r.status_code == 200, r.text
        assert len(r.json()["messages"]) == 2

        # Bob cannot read, continue or delete it; it looks like it does not exist.
        assert (
            await c.get(f"/api/v1/chat/conversations/{conv_id}", headers=h_bob)
        ).status_code == 404
        r = await c.post(
            "/api/v1/chat/",
            json={
                "message": "continue",
                "knowledge_base_ids": [kb],
                "stream": False,
                "conversation_id": conv_id,
            },
            headers=h_bob,
        )
        assert r.status_code == 404, r.text
        assert (
            await c.delete(f"/api/v1/chat/conversations/{conv_id}", headers=h_bob)
        ).status_code == 404
        assert (await c.get("/api/v1/chat/conversations", headers=h_bob)).json() == []

        # Alice can follow up in her own conversation and then delete it.
        r = await c.post(
            "/api/v1/chat/",
            json={
                "message": "and for monthly plans?",
                "knowledge_base_ids": [kb],
                "stream": False,
                "conversation_id": conv_id,
            },
            headers=h_alice,
        )
        assert r.status_code == 200, r.text
        assert (
            await c.delete(f"/api/v1/chat/conversations/{conv_id}", headers=h_alice)
        ).status_code == 204


async def test_chunks_record_the_chunking_config_they_were_made_with(env):  # noqa: F811
    from sqlalchemy import text

    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"chk-{uuid.uuid4().hex[:6]}")
        await upload(c, h, kb, "p.pdf", make_pdf({"T": "some policy text about refunds"}))
    async with maker() as s:
        rows = (
            await s.execute(
                text("SELECT metadata->'chunking' FROM chunks WHERE knowledge_base_id = :k"),
                {"k": kb},
            )
        ).scalars().all()
    assert rows, "no chunks were created"
    for chunking in rows:
        assert chunking["strategy"] == "structure_aware"
        assert chunking["chunk_size"] == 512 and chunking["chunk_overlap"] == 64
