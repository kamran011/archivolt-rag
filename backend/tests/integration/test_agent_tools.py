"""Agent tools on real Postgres: access control, tenancy, wildcard safety, and the persisted,
admin-readable audit trail of an agentic chat request."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.retrieval.access import AccessScope
from app.domains.tools.base import ToolContext, ToolExecutor
from app.domains.tools.registry import default_registry
from app.main import app
from app.models.organization_member import OrgRole
from tests.integration.test_document_access import RecordingLLM, add_member, upload_doc
from tests.integration.test_traces import ScriptedLLM as AnswerLLM
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    onboard,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


def executor(db, org, kb, scope, role=OrgRole.member) -> ToolExecutor:
    return ToolExecutor(
        default_registry,
        ToolContext(db=db, org_id=uuid.UUID(org), kb_ids=[uuid.UUID(kb)], scope=scope, role=role),
    )


@pytest.fixture
async def world(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"tools-{uuid.uuid4().hex[:6]}")
        org = h["X-Organization-Id"]
        await upload_doc(c, h, kb, "handbook.pdf", {"Refunds": "Annual plans refund window is 30 days."})
        await upload_doc(
            c, h, kb, "secret-plan.pdf", {"Merger": "Confidential acquisition codename Falcon."},
            restricted=True,
        )
        member, h_member = await add_member(c, h)
        yield {"c": c, "h": h, "kb": kb, "org": org, "member": member, "h_member": h_member,
               "env": env, "orgs": orgs}


async def test_document_lookup_opens_document_and_respects_access(world):
    maker = world["env"][0]
    org, kb = world["org"], world["kb"]
    async with maker() as s:
        member_scope = AccessScope(user_id=world["member"], is_admin=False)
        admin_scope = AccessScope(user_id=uuid.uuid4(), is_admin=True)

        r = await executor(s, org, kb, member_scope).call("document_lookup", {"title": "handbook"})
        assert r.ok and r.chunks and "30 days" in r.chunks[0].content
        assert r.chunks[0].retrieval_method == "lookup"

        # The member cannot open the restricted document by title...
        r = await executor(s, org, kb, member_scope).call("document_lookup", {"title": "secret"})
        assert r.ok and r.chunks == [] and "no document" in r.content
        # ...no scope at all fails closed...
        r = await executor(s, org, kb, None).call("document_lookup", {"title": "secret"})
        assert r.chunks == []
        # ...an admin can.
        r = await executor(s, org, kb, admin_scope, OrgRole.admin).call(
            "document_lookup", {"title": "secret"}
        )
        assert r.chunks and "Falcon" in r.chunks[0].content


@pytest.mark.parametrize("title", ["%", "_", "%%", "h_ndbook", "hand%", "\\"])
async def test_document_lookup_treats_title_as_literal_text(world, title):
    """LIKE wildcards in the argument must not widen the match."""
    maker = world["env"][0]
    async with maker() as s:
        scope = AccessScope(user_id=uuid.uuid4(), is_admin=True)
        r = await executor(s, world["org"], world["kb"], scope, OrgRole.admin).call(
            "document_lookup", {"title": title if len(title) >= 2 else title + title}
        )
        assert r.ok and r.chunks == []


async def test_tools_cannot_read_another_tenants_documents(world):
    c, maker = world["c"], world["env"][0]
    h_b, kb_b = await onboard(c, world["orgs"], uuid.uuid4(), f"other-{uuid.uuid4().hex[:6]}")
    org_b = h_b["X-Organization-Id"]
    admin = AccessScope(user_id=uuid.uuid4(), is_admin=True)
    async with maker() as s:
        # Org B's context pointed at org A's knowledge base: nothing comes back.
        ex = executor(s, org_b, world["kb"], admin, OrgRole.admin)
        assert (await ex.call("document_lookup", {"title": "handbook"})).chunks == []
        assert (await ex.call("knowledge_base_search", {"query": "refund window"})).chunks == []


async def test_agentic_chat_runs_tools_and_persists_an_admin_readable_audit(world, monkeypatch):
    c, kb = world["c"], world["kb"]

    planner_replies = [
        {"action": "tool", "tool": "document_lookup", "args": {"title": "secret"}},
        {"action": "tool", "tool": "calculator", "args": {"expression": "30 * 12"}},
        {"action": "tool", "tool": "calculator", "args": {"expression": "__import__('os')"}},
        {"action": "tool", "tool": "no_such_tool", "args": {}},
    ]

    class Planner:
        def __init__(self):
            self.replies = [json.dumps(r) for r in planner_replies]
            self.prompts = []

        async def generate(self, messages, temperature=0.1, max_tokens=2048):
            from app.providers.llm.base import LLMResponse

            self.prompts.append(messages[-1]["content"])
            body = self.replies.pop(0) if self.replies else '{"action": "finish"}'
            return LLMResponse(content=body, prompt_tokens=5, completion_tokens=5, model="p",
                               finish_reason="stop")

    planner, answer = Planner(), AnswerLLM()
    monkeypatch.setattr("app.domains.agent.retrieval_agent.get_llm_provider", lambda m: planner)
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda m: answer)

    async def rerank(query, chunks, top_k=10):
        return [ch.model_copy(update={"score": 0.9}) for ch in chunks[:top_k]]

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    RecordingLLM.prompts.clear()

    r = await c.post(
        "/api/v1/chat/",
        json={"message": "What is the refund window for annual plans?",
              "knowledge_base_ids": [kb], "stream": False, "agentic": True},
        headers=world["h_member"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert not body["abstained"], body
    trace_id = body["retrieval_metadata"]["trace_id"]
    assert "Falcon" not in json.dumps(body)  # the member's lookup of the secret found nothing
    # Computed value reached the planner, but is not a source.
    assert any("30 * 12 = 360" in p for p in planner.prompts)
    assert all("tool_calls" not in k for k in body)  # audit is internal, not in the response body

    # Owner reads the audit trail; a member cannot.
    r = await c.get(f"/api/v1/observability/traces/{trace_id}/tool-calls", headers=world["h"])
    assert r.status_code == 200, r.text
    calls = [(x["tool"], x["status"]) for x in r.json()]
    assert calls == [
        ("knowledge_base_search", "ok"),   # step 0: search on the question itself
        ("document_lookup", "ok"),
        ("calculator", "ok"),
        ("calculator", "error"),            # the tool ran and rejected the unsafe input
        ("no_such_tool", "unknown_tool"),
    ]
    lookup = next(x for x in r.json() if x["tool"] == "document_lookup")
    assert lookup["arguments"] == {"title": "secret"} and lookup["result_chunks"] == 0
    assert (
        await c.get(f"/api/v1/observability/traces/{trace_id}/tool-calls", headers=world["h_member"])
    ).status_code == 403

    # Other organizations see nothing for this trace.
    h_b, _ = await onboard(c, world["orgs"], uuid.uuid4(), f"o2-{uuid.uuid4().hex[:6]}")
    other = await c.get(f"/api/v1/observability/traces/{trace_id}/tool-calls", headers=h_b)
    assert other.status_code == 200 and other.json() == []
