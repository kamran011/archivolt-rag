"""Document-level access control against real Postgres.

A restricted document must not reach an unauthorized member through ANY path: every
retrieval strategy, tree outlines (which are shown to an LLM), neighbor expansion, the
agent, the debug endpoint, document/chunk/tree/download endpoints, the chat LLM context and
persisted traces."""

import json
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.expansion import expand_with_neighbors
from app.main import app
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    token,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

SECRET = "Falcon"
OPEN_TEXT = "Annual plans have a refund window of 30 days."
SECRET_TEXT = "Confidential merger with Acme, codename Falcon. Do not disclose the acquisition."


class RecordingLLM:
    """Records every prompt it is shown. Answers/verifies/navigates with fixed replies."""

    prompts: list[str] = []

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        from app.providers.llm.base import LLMResponse

        text = "\n".join(m["content"] for m in messages)
        RecordingLLM.prompts.append(text)
        last = messages[-1]["content"]
        if "fact-checker" in last:
            body = json.dumps(
                [{"claim": "c", "status": "supported", "supporting_sources": [1], "confidence": 1}]
            )
        elif "contradict" in last:
            body = "[]"
        elif "navigat" in last.lower() and "[d" in last:
            refs = re.findall(r"\[(d\d+:[^\]]+)\]", last)
            body = json.dumps({"nodes": refs})
        elif '"action"' in last and "finish" in last:
            body = json.dumps({"action": "finish"})
        else:
            body = "Answer based on the sources [Source 1]."
        return LLMResponse(
            content=body, prompt_tokens=10, completion_tokens=5, model="f", finish_reason="stop"
        )

    async def stream(self, messages, temperature=0.1, max_tokens=2048):
        yield "ok"


@pytest.fixture
def llm(monkeypatch):
    RecordingLLM.prompts = []
    fake = RecordingLLM()
    for target in (
        "app.domains.rag.service.get_llm_provider",
        "app.domains.agent.retrieval_agent.get_llm_provider",
        "app.domains.retrieval.engines.tree_engine.get_llm_provider",
    ):
        monkeypatch.setattr(target, lambda model, f=fake: f)

    async def rerank(query, chunks, top_k=10):
        return [c.model_copy(update={"score": 0.9}) for c in chunks[:top_k]]

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    return fake


async def add_member(c, h_owner, role="member") -> tuple[uuid.UUID, dict]:
    user = uuid.uuid4()
    org = h_owner["X-Organization-Id"]
    r = await c.post(
        f"/api/v1/organizations/{org}/members",
        json={"user_id": str(user), "role": role},
        headers=h_owner,
    )
    assert r.status_code == 201, r.text
    return user, {**token(user), "X-Organization-Id": org}


async def upload_doc(c, h, kb, name, sections, restricted=False, tags=""):
    r = await c.post(
        f"/api/v1/knowledge-bases/{kb}/documents/upload",
        files={"file": (name, make_pdf(sections), "application/pdf")},
        data={"restricted": str(restricted).lower(), "tags": tags},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def world(env, llm):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h_owner, kb = await onboard(c, orgs, uuid.uuid4(), f"acl-{uuid.uuid4().hex[:6]}")
        open_doc = await upload_doc(c, h_owner, kb, "open.pdf", {"Refunds": OPEN_TEXT})
        secret_doc = await upload_doc(
            c, h_owner, kb, "secret.pdf", {"Acquisition Plans": SECRET_TEXT}, restricted=True
        )
        member, h_member = await add_member(c, h_owner)
        yield {
            "c": c, "kb": kb, "owner": h_owner, "member": h_member, "member_id": member,
            "open": open_doc, "secret": secret_doc, "env": env,
        }


def search_body(kb, strategy, query="confidential merger acquisition codename"):
    return {"query": query, "knowledge_base_ids": [kb], "strategy": strategy, "top_k": 20}


@pytest.mark.parametrize("strategy", ["semantic", "keyword", "hybrid", "tree"])
async def test_member_never_retrieves_restricted_content(world, strategy):
    c, kb = world["c"], world["kb"]
    r = await c.post(
        "/api/v1/retrieval/search", json=search_body(kb, strategy), headers=world["member"]
    )
    assert r.status_code == 200, r.text
    assert SECRET not in json.dumps(r.json()), f"{strategy} leaked restricted content"

    # ...while the owner (admin) can retrieve it, so the assertion above is meaningful.
    r = await c.post(
        "/api/v1/retrieval/search", json=search_body(kb, strategy), headers=world["owner"]
    )
    assert SECRET in json.dumps(r.json()), f"{strategy}: owner should see the document"


async def test_restricted_outline_never_reaches_the_navigation_llm(world):
    c, kb = world["c"], world["kb"]
    RecordingLLM.prompts.clear()
    await c.post(
        "/api/v1/retrieval/search", json=search_body(kb, "tree"), headers=world["member"]
    )
    seen = "\n".join(RecordingLLM.prompts)
    assert "Acquisition Plans" not in seen and SECRET not in seen
    assert "Refunds" in seen  # the open document's outline was shown (test is meaningful)


async def test_debug_endpoint_hides_restricted_content(world):
    c, kb = world["c"], world["kb"]
    r = await c.post(
        "/api/v1/retrieval/debug",
        json={"query": "confidential merger", "knowledge_base_ids": [kb], "top_k": 10},
        headers=world["member"],
    )
    assert r.status_code == 200, r.text
    assert SECRET not in json.dumps(r.json())


async def test_document_endpoints_hide_restricted_document(world):
    c, kb, secret = world["c"], world["kb"], world["secret"]
    base = f"/api/v1/knowledge-bases/{kb}/documents"
    m = world["member"]

    listing = (await c.get(f"{base}/", headers=m)).json()
    assert [d["id"] for d in listing] == [world["open"]]
    for suffix in ("", "/chunks", "/tree", "/download", "/versions", "/access"):
        r = await c.get(f"{base}/{secret}{suffix}", headers=m)
        assert r.status_code in (403, 404), f"GET {suffix or '/'} -> {r.status_code}"
    r = await c.delete(f"{base}/{secret}", headers=m)
    assert r.status_code in (403, 404)

    # Owner still sees everything.
    assert {d["id"] for d in (await c.get(f"{base}/", headers=world["owner"])).json()} == {
        world["open"], secret,
    }
    assert (await c.get(f"{base}/{secret}/chunks", headers=world["owner"])).status_code == 200


async def test_chat_context_and_trace_exclude_restricted_content(world, llm):
    c, kb = world["c"], world["kb"]
    RecordingLLM.prompts.clear()
    r = await c.post(
        "/api/v1/chat/",
        json={
            "message": "Tell me about the confidential merger with Acme",
            "knowledge_base_ids": [kb],
            "stream": False,
        },
        headers=world["member"],
    )
    assert r.status_code == 200, r.text
    assert SECRET not in "\n".join(RecordingLLM.prompts), "LLM was shown restricted evidence"
    assert SECRET not in json.dumps(r.json())

    # The trace of that request must not reference the restricted document either.
    trace_id = r.json()["retrieval_metadata"]["trace_id"]
    r = await c.get(f"/api/v1/observability/traces/{trace_id}", headers=world["owner"])
    assert world["secret"] not in json.dumps(r.json())

    # Same question from the owner does reach the restricted evidence.
    RecordingLLM.prompts.clear()
    await c.post(
        "/api/v1/chat/",
        json={
            "message": "Tell me about the confidential merger with Acme",
            "knowledge_base_ids": [kb],
            "stream": False,
        },
        headers=world["owner"],
    )
    assert SECRET in "\n".join(RecordingLLM.prompts)


async def test_agent_and_neighbor_expansion_respect_scope(world):
    from sqlalchemy import select

    from app.domains.agent.retrieval_agent import retrieval_agent
    from app.domains.retrieval.mapping import row_to_retrieved_chunk
    from app.models import Chunk, Document

    maker = world["env"][0]
    org = uuid.UUID(world["owner"]["X-Organization-Id"])
    kb = uuid.UUID(world["kb"])
    member_scope = AccessScope(user_id=world["member_id"], is_admin=False)

    async with maker() as s:
        result = await retrieval_agent.run(
            s, org, "confidential merger acquisition", [kb], scope=member_scope
        )
        assert result.chunks, "agent should still find the open document"
        assert all(SECRET not in c.content for c in result.chunks)

        # Neighbor expansion seeded from the restricted document's own chunk must not
        # pull in its neighbors for an unauthorized scope (and works for an admin).
        row = (
            await s.execute(
                select(Chunk, Document)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.id == uuid.UUID(world["secret"]))
                .limit(1)
            )
        ).first()
        seed = row_to_retrieved_chunk(row[0], row[1], 0.9, "semantic")
        expanded = await expand_with_neighbors(s, org, [seed], scope=member_scope)
        assert [c.chunk_id for c in expanded] == [seed.chunk_id]  # nothing added
        # No scope at all fails closed too.
        assert len(await expand_with_neighbors(s, org, [seed])) == 1


async def test_grant_and_revoke_access(world):
    c, kb, secret = world["c"], world["kb"], world["secret"]
    base = f"/api/v1/knowledge-bases/{kb}/documents/{secret}"
    member_id = world["member_id"]

    async def member_sees() -> bool:
        r = await c.post(
            "/api/v1/retrieval/search", json=search_body(kb, "keyword"), headers=world["member"]
        )
        return SECRET in json.dumps(r.json())

    assert not await member_sees()

    # Only owners/admins manage grants; a member cannot grant themselves access.
    r = await c.post(f"{base}/access", json={"user_id": str(member_id)}, headers=world["member"])
    assert r.status_code in (403, 404)
    assert not await member_sees()

    # Cannot grant to someone outside the org.
    r = await c.post(f"{base}/access", json={"user_id": str(uuid.uuid4())}, headers=world["owner"])
    assert r.status_code == 422

    r = await c.post(f"{base}/access", json={"user_id": str(member_id)}, headers=world["owner"])
    assert r.status_code == 204, r.text
    assert await member_sees()
    assert (await c.get(f"{base}/chunks", headers=world["member"])).status_code == 200
    assert (await c.get(f"{base}/access", headers=world["owner"])).json() == [str(member_id)]

    r = await c.delete(f"{base}/access/{member_id}", headers=world["owner"])
    assert r.status_code == 204, r.text
    assert not await member_sees()


async def test_uploader_sees_own_restricted_document_and_versions_inherit_restriction(world):
    c, kb = world["c"], world["kb"]
    uploader, h_up = await add_member(c, world["owner"])
    mine = await upload_doc(c, h_up, kb, "mine.pdf", {"Notes": "private uploader notes zebra"}, True)

    base = f"/api/v1/knowledge-bases/{kb}/documents"
    assert (await c.get(f"{base}/{mine}", headers=h_up)).status_code == 200
    assert (await c.get(f"{base}/{mine}", headers=world["member"])).status_code == 404

    # A new version of a restricted document stays restricted.
    r = await c.post(
        f"{base}/{mine}/versions",
        files={"file": ("mine2.pdf", make_pdf({"Notes": "private notes v2 zebra"}), "application/pdf")},
        headers=h_up,
    )
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["restricted"] is True
    assert (await c.get(f"{base}/{v2['id']}", headers=world["member"])).status_code == 404


async def test_admin_can_restrict_an_existing_document_and_set_tags(world):
    c, kb, open_doc = world["c"], world["kb"], world["open"]
    base = f"/api/v1/knowledge-bases/{kb}/documents/{open_doc}"

    r = await c.patch(base, json={"restricted": True, "tags": ["Legal ", "legal", "hr"]},
                      headers=world["owner"])
    assert r.status_code == 200, r.text
    assert r.json()["restricted"] is True and r.json()["tags"] == ["Legal", "hr", "legal"]

    # A member cannot change access settings.
    r = await c.patch(base, json={"restricted": False}, headers=world["member"])
    assert r.status_code in (403, 404)
    r = await c.post(
        "/api/v1/retrieval/search", json=search_body(kb, "keyword", "refund window annual"),
        headers=world["member"],
    )
    assert r.json()["chunks"] == []


async def test_tag_and_as_of_filters(world):
    c, kb = world["c"], world["kb"]
    await c.patch(
        f"/api/v1/knowledge-bases/{kb}/documents/{world['open']}",
        json={"tags": ["billing"], "effective_date": "2024-01-01T00:00:00Z"},
        headers=world["owner"],
    )

    def body(filters):
        return {**search_body(kb, "keyword", "refund window annual plans"), "filters": filters}

    async def n(filters):
        r = await c.post("/api/v1/retrieval/search", json=body(filters), headers=world["owner"])
        assert r.status_code == 200, r.text
        return len(r.json()["chunks"])

    assert await n({"tags": ["billing"]}) >= 1
    assert await n({"tags": ["unrelated"]}) == 0
    assert await n({"as_of": "2025-01-01T00:00:00Z"}) >= 1  # in force by then
    assert await n({"as_of": "2023-01-01T00:00:00Z"}) == 0  # not yet effective
    assert await n({"effective_from": "2024-06-01T00:00:00Z"}) == 0
    assert await n({"effective_to": "2024-06-01T00:00:00Z"}) >= 1
