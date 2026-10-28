"""Human handoff end to end: settings API, chat trigger, inbox, notification job."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domains.escalation import notify
from app.main import app
from app.models.job import Job
from tests.integration.test_traces import ScriptedLLM
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    token,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

SETTINGS = {
    "enabled": True,
    "triggers": ["user_request", "frustration", "abstain"],
    "emails": [],
    "slack_webhook_url": "https://hooks.slack.com/services/T0/B0/secret",
    "customer_message": "A teammate will follow up shortly.",
}


@pytest.fixture
def scripted(monkeypatch, env):  # noqa: F811
    maker, _ = env
    monkeypatch.setattr("app.domains.rag.service.get_llm_provider", lambda model: ScriptedLLM())

    async def rerank(query, chunks, top_k=10):
        return [c.model_copy(update={"score": 0.9}) for c in chunks[:top_k]]

    monkeypatch.setattr("app.domains.rag.service._reranker.rerank", rerank)
    monkeypatch.setattr("app.domains.chat.router.AsyncSessionLocal", maker)
    monkeypatch.setattr("app.domains.escalation.detector.typesafe.configured", lambda: False)
    monkeypatch.setattr("app.domains.escalation.notify.sessions.new_session", maker)


async def chat(c, h, kb, message, conversation_id=None):
    payload = {"message": message, "knowledge_base_ids": [kb], "stream": True}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    r = await c.post("/api/v1/chat/", json=payload, headers=h)
    assert r.status_code == 200, r.text
    return [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]


async def test_handoff_end_to_end(env, scripted, monkeypatch):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"esc-{uuid.uuid4().hex[:6]}")
        await upload(c, h, kb, "policy.pdf",
                     make_pdf({"Refunds": "Annual plans can be refunded within 30 days."}))

        # Disabled by default: asking for a human does nothing.
        events = await chat(c, h, kb, "Can I talk to a human please?")
        assert not [e for e in events if e["type"] == "handoff"]

        r = await c.put("/api/v1/escalations/settings", json=SETTINGS, headers=h)
        assert r.status_code == 200, r.text
        bad = {**SETTINGS, "slack_webhook_url": "https://evil.example/x"}
        assert (await c.put("/api/v1/escalations/settings", json=bad, headers=h)).status_code == 422

        events = await chat(c, h, kb, "Can I talk to a human please?")
        handoff = [e for e in events if e["type"] == "handoff"]
        assert handoff and handoff[0]["status"] == "created", events
        assert handoff[0]["reasons"] == ["user_request"]
        assert handoff[0]["message"] == "A teammate will follow up shortly."
        conv = handoff[0]["conversation_id"]

        # A repeat trigger in the same conversation does not open (or notify) a second one.
        again = await chat(c, h, kb, "I want to speak with a real person", conv)
        assert [e for e in again if e["type"] == "handoff"][0]["status"] == "already_open"

        listed = (await c.get("/api/v1/escalations/?status=open", headers=h)).json()
        assert len(listed) == 1 and listed[0]["conversation_id"] == conv
        esc_id = listed[0]["id"]
        detail = (await c.get(f"/api/v1/escalations/{esc_id}", headers=h)).json()
        assert [m["role"] for m in detail["transcript"]][:2] == ["user", "assistant"]

        # Exactly one notification job, delivered by the worker handler.
        async with maker() as s:
            jobs = (await s.execute(select(Job).where(Job.kind == "escalation_notify"))).scalars().all()
            job = [j for j in jobs if j.payload["escalation_id"] == esc_id]
        assert len(job) == 1
        sent = []

        async def fake_slack(url, text):
            sent.append((url, text))

        monkeypatch.setattr(notify, "_send_slack", fake_slack)
        await notify.escalation_notify_handler.run(job[0])
        assert sent and "Customer asked for a human" in sent[0][1]
        assert f"/dashboard/escalations?id={esc_id}" in sent[0][1]
        detail = (await c.get(f"/api/v1/escalations/{esc_id}", headers=h)).json()
        assert detail["delivery"] == {"slack": "sent", "email": "not_configured"}

        # Members cannot read the inbox (it exposes other users' conversations).
        member = uuid.uuid4()
        org = h["X-Organization-Id"]
        r = await c.post(f"/api/v1/organizations/{org}/members",
                         json={"user_id": str(member), "role": "member"}, headers=h)
        assert r.status_code == 201, r.text
        h_member = {**token(member), "X-Organization-Id": org}
        assert (await c.get("/api/v1/escalations/", headers=h_member)).status_code == 403

        r = await c.post(f"/api/v1/escalations/{esc_id}/resolve", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "resolved"
        assert (await c.get("/api/v1/escalations/?status=open", headers=h)).json() == []
