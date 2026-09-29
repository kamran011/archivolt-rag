"""CAG on real Postgres: eligibility, access control, versions and the chat path."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.cag import load_cag_context
from app.main import app
from tests.integration.test_document_access import RecordingLLM, add_member
from tests.integration.test_hierarchical_retrieval import upload_md
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    onboard,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

REFUNDS = "# Refunds\n\nAnnual plans have a refund period of thirty days.\n"
SHIPPING = "# Shipping\n\nOrders ship within five business days by carrier.\n"
SECRET = "# Merger\n\nConfidential acquisition codename Falcon is planned.\n"
ADMIN = AccessScope(user_id=uuid.uuid4(), is_admin=True)


@pytest.fixture
async def world(env, monkeypatch):  # noqa: F811
    RecordingLLM.prompts = []
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda m: RecordingLLM())
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"cag-{uuid.uuid4().hex[:6]}")
        org = h["X-Organization-Id"]
        await upload_md(c, h, kb, "refunds.md", REFUNDS)
        await upload_md(c, h, kb, "shipping.md", SHIPPING)
        member, h_member = await add_member(c, h)
        yield {"c": c, "h": h, "kb": kb, "org": org, "member": member, "h_member": h_member,
               "env": env, "orgs": orgs}


async def enable(w, on=True):
    r = await w["c"].patch(f"/api/v1/knowledge-bases/{w['kb']}", json={"cag_enabled": on},
                           headers=w["h"])
    assert r.status_code == 200, r.text
    assert r.json()["cag_enabled"] is on


async def ask(w, h=None, mode="cag", msg="What is the refund period for annual plans?"):
    r = await w["c"].post(
        "/api/v1/chat/",
        json={"message": msg, "knowledge_base_ids": [w["kb"]], "stream": False, "mode": mode},
        headers=h or w["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_only_admins_control_cag_and_it_is_off_by_default(world):
    c = world["c"]
    kb = (await c.get(f"/api/v1/knowledge-bases/{world['kb']}", headers=world["h"])).json()
    assert kb["cag_enabled"] is False
    r = await c.patch(f"/api/v1/knowledge-bases/{world['kb']}", json={"cag_enabled": True},
                      headers=world["h_member"])
    assert r.status_code == 403
    r = await c.post("/api/v1/knowledge-bases/", json={"name": "Sneaky", "cag_enabled": True},
                     headers=world["h_member"])
    assert r.status_code == 403
    r = await c.post("/api/v1/knowledge-bases/", json={"name": "Fine KB"}, headers=world["h_member"])
    assert r.status_code == 201


async def test_cag_mode_answers_from_the_whole_kb(world):
    await enable(world)
    body = await ask(world)
    assert not body["abstained"], body
    assert body["retrieval_metadata"]["answer_mode"] == "cag"
    prompt = RecordingLLM.prompts[0]
    assert "refund period" in prompt and "ship within five business days" in prompt  # both docs
    trace = (await world["c"].get(
        f"/api/v1/observability/traces/{body['retrieval_metadata']['trace_id']}",
        headers=world["h"])).json()
    assert trace["strategy"] == "cag" and len(trace["stages"]["selected"]) == 2


async def test_cag_falls_back_to_rag_when_the_kb_has_not_opted_in(world):
    body = await ask(world)  # cag_enabled is False
    md = body["retrieval_metadata"]
    assert md["answer_mode"] == "rag" and "not enabled" in md["cag_note"]


async def test_oversized_kb_is_not_truncated_it_falls_back(world, monkeypatch):
    await enable(world)
    monkeypatch.setattr(settings, "CAG_MAX_TOKENS", 5)
    body = await ask(world)
    md = body["retrieval_metadata"]
    assert md["answer_mode"] == "rag" and "too large" in md["cag_note"]


async def test_restricted_documents_are_never_in_a_members_cag_context(world):
    await enable(world)
    await upload_md(world["c"], world["h"], world["kb"], "merger.md", SECRET, restricted=True)
    maker = world["env"][0]
    org, kb = uuid.UUID(world["org"]), uuid.UUID(world["kb"])
    member_scope = AccessScope(user_id=world["member"], is_admin=False)
    async with maker() as s:
        member_ctx = await load_cag_context(s, org, [kb], member_scope)
        admin_ctx = await load_cag_context(s, org, [kb], ADMIN)
        no_scope = await load_cag_context(s, org, [kb], None)
    assert all("Falcon" not in c.content for c in member_ctx.chunks)
    assert all("Falcon" not in c.content for c in no_scope.chunks)  # fail closed
    assert any("Falcon" in c.content for c in admin_ctx.chunks)
    assert member_ctx.total_tokens < admin_ctx.total_tokens  # size is measured per caller

    RecordingLLM.prompts.clear()
    await ask(world, world["h_member"])
    assert "Falcon" not in "\n".join(RecordingLLM.prompts)
    RecordingLLM.prompts.clear()
    await ask(world, world["h"], msg="What is the refund period? Also the acquisition codename?")
    assert "Falcon" in "\n".join(RecordingLLM.prompts)


async def test_only_current_versions_are_loaded(world):
    await enable(world)
    c, kb = world["c"], world["kb"]
    listing = (await c.get(f"/api/v1/knowledge-bases/{kb}/documents/", headers=world["h"])).json()
    refunds = next(d for d in listing if d["title"] == "refunds")
    r = await c.post(
        f"/api/v1/knowledge-bases/{kb}/documents/{refunds['id']}/versions",
        files={"file": ("refunds.md",
                        b"# Refunds\n\nAnnual plans now have a refund period of sixty days.\n",
                        "text/markdown")},
        headers=world["h"],
    )
    assert r.status_code == 201, r.text
    RecordingLLM.prompts.clear()
    await ask(world)
    prompt = RecordingLLM.prompts[0]
    assert "sixty days" in prompt and "thirty days" not in prompt


async def test_other_tenants_cannot_load_a_kb_they_do_not_own(world):
    await enable(world)
    c, maker = world["c"], world["env"][0]
    h_b, _ = await onboard(c, world["orgs"], uuid.uuid4(), f"cagb-{uuid.uuid4().hex[:6]}")
    async with maker() as s:
        ctx = await load_cag_context(
            s, uuid.UUID(h_b["X-Organization-Id"]), [uuid.UUID(world["kb"])], ADMIN
        )
    assert not ctx.eligible and ctx.chunks == [] and "not found" in ctx.reason


async def test_cag_info_endpoint_reports_eligibility_without_loading_text(world):
    c, kb = world["c"], world["kb"]
    info = (await c.get(f"/api/v1/knowledge-bases/{kb}/cag", headers=world["h"])).json()
    assert info == {"enabled": False, "eligible": False,
                    "reason": "CAG is not enabled for this knowledge base",
                    "tokens": 0, "limit": settings.CAG_MAX_TOKENS}
    await enable(world)
    info = (await c.get(f"/api/v1/knowledge-bases/{kb}/cag", headers=world["h"])).json()
    assert info["enabled"] and info["eligible"] and 0 < info["tokens"] <= info["limit"]
    assert json.dumps(info).count("refund") == 0  # sizes only, never content


async def test_cag_answer_abstains_for_questions_the_kb_does_not_cover(world):
    await enable(world)
    body = await ask(world, msg="What is the airspeed velocity of an unladen swallow?")
    assert body["abstained"] is True and body["citations"] == []
