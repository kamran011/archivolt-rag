"""Web search through the real API and Postgres: org opt-in, per-request toggle, external
citations, and the audit trail. The search provider and LLMs are scripted."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.providers.web_search.base import WebResult, WebSearchProvider
from tests.integration.test_document_access import add_member, upload_doc
from tests.integration.test_traces import ScriptedLLM as AnswerLLM
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    onboard,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


class Provider(WebSearchProvider):
    def __init__(self):
        self.calls = []

    async def search(self, query, max_results):
        self.calls.append(query)
        return [WebResult(title="EU consumer rules", url="https://eu.example/rules",
                          snippet="The EU consumer refund period is 14 days from delivery.")]


class WebAnswerLLM(AnswerLLM):
    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        from app.providers.llm.base import LLMResponse

        r = await super().generate(messages, temperature, max_tokens)
        prompt = messages[-1]["content"]
        if "fact-checker" not in prompt and "contradict" not in prompt:
            return LLMResponse(content="The EU refund period is 14 days [Source 1].",
                               prompt_tokens=1, completion_tokens=1, model="f",
                               finish_reason="stop")
        return r


@pytest.fixture
async def world(env, monkeypatch):  # noqa: F811
    provider = Provider()
    monkeypatch.setattr(settings, "ENABLE_WEB_SEARCH", True)
    monkeypatch.setattr("app.domains.tools.web_search.get_web_search_provider", lambda: provider)
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda m: WebAnswerLLM())

    async def rerank(query, chunks, top_k=10):
        scored = [
            c.model_copy(update={"score": c.score if c.retrieval_method == "web" else 0.5})
            for c in chunks
        ]
        return sorted(scored, key=lambda c: c.score, reverse=True)[:top_k]  # best first

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"web-{uuid.uuid4().hex[:6]}")
        await upload_doc(c, h, kb, "office.pdf", {"Office": "Our office is closed on public holidays."})
        member, h_member = await add_member(c, h)
        yield {"c": c, "h": h, "kb": kb, "org": h["X-Organization-Id"], "provider": provider,
               "h_member": h_member, "orgs": orgs}


async def ask(w, h=None, *, web=True, msg="What is the EU consumer refund period?"):
    r = await w["c"].post(
        "/api/v1/chat/",
        json={"message": msg, "knowledge_base_ids": [w["kb"]], "stream": False, "web_search": web},
        headers=h or w["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()


async def enable_org(w):
    r = await w["c"].patch(
        f"/api/v1/organizations/{w['org']}",
        json={"settings": {"web_search_enabled": True}},
        headers=w["h"],
    )
    assert r.status_code == 200, r.text


async def test_web_is_off_until_the_org_admin_opts_in(world):
    body = await ask(world)  # user asks for web, org has not opted in
    assert world["provider"].calls == [] and body["abstained"]

    # A member cannot switch it on for the organization.
    r = await world["c"].patch(
        f"/api/v1/organizations/{world['org']}",
        json={"settings": {"web_search_enabled": True}},
        headers=world["h_member"],
    )
    assert r.status_code == 403
    assert (await ask(world))["abstained"] and world["provider"].calls == []


async def test_user_must_also_ask_for_web_on_each_request(world):
    await enable_org(world)
    body = await ask(world, web=False)
    assert world["provider"].calls == [] and body["abstained"]


async def test_web_fallback_returns_a_labelled_external_citation_and_is_audited(world):
    await enable_org(world)
    body = await ask(world)
    assert not body["abstained"], body
    assert world["provider"].calls == ["What is the EU consumer refund period?"]

    [citation] = body["citations"]
    assert citation["source_type"] == "external" and citation["url"] == "https://eu.example/rules"
    assert body["retrieval_metadata"]["strategies_tried"][-1] == "web"

    trace_id = body["retrieval_metadata"]["trace_id"]
    calls = await world["c"].get(
        f"/api/v1/observability/traces/{trace_id}/tool-calls", headers=world["h"]
    )
    assert [(x["tool"], x["status"], x["result_chunks"]) for x in calls.json()] == [
        ("web_search", "ok", 1)
    ]
    trace = (await world["c"].get(f"/api/v1/observability/traces/{trace_id}",
                                  headers=world["h"])).json()
    # the trace records the external evidence and that it was used
    assert any(s["method"] == "web" for s in trace["stages"]["selected"])
    assert "Falcon" not in json.dumps(body)


async def test_internal_evidence_is_preferred_and_web_not_called(world):
    await enable_org(world)
    await upload_doc(world["c"], world["h"], world["kb"], "refunds.pdf",
                     {"Refunds": "The EU consumer refund period is 30 days for our customers."})
    body = await ask(world)
    assert world["provider"].calls == [] and not body["abstained"]
    assert all(c["source_type"] == "internal" for c in body["citations"])
