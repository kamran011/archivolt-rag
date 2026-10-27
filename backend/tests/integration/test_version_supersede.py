"""A new document version replaces the old one only after it is ingested successfully."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


async def _docs(c, h, kb):
    r = await c.get(f"/api/v1/knowledge-bases/{kb}/documents/", headers=h)
    assert r.status_code == 200, r.text
    return {d["id"]: d for d in r.json()}


async def _search(c, h, kb, q):
    r = await c.post("/api/v1/retrieval/search",
                     json={"query": q, "knowledge_base_ids": [kb], "strategy": "keyword"},
                     headers=h)
    assert r.status_code == 200, r.text
    return [x["document_id"] for x in r.json()["chunks"]]


async def _new_version(c, h, kb, doc, pdf):
    return await c.post(f"/api/v1/knowledge-bases/{kb}/documents/{doc}/versions",
                        files={"file": ("policy.pdf", pdf, "application/pdf")}, headers=h)


async def test_failed_new_version_keeps_previous_current(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"ver-{uuid.uuid4().hex[:6]}")
        v1 = await upload(c, h, kb, "policy.pdf",
                          make_pdf({"Refunds": "Annual plans are refundable within 30 days."}))

        # A version with no extractable text fails ingestion.
        r = await _new_version(c, h, kb, v1, make_pdf({}))
        assert r.status_code == 201, r.text
        v2 = r.json()["id"]

        docs = await _docs(c, h, kb)
        assert docs[v2]["status"] == "failed"
        assert docs[v1]["is_current"] is True  # still the live version
        assert v1 in await _search(c, h, kb, "refundable annual")


async def test_successful_new_version_supersedes_previous(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"ver-{uuid.uuid4().hex[:6]}")
        v1 = await upload(c, h, kb, "policy.pdf",
                          make_pdf({"Refunds": "Annual plans are refundable within 30 days."}))
        r = await _new_version(c, h, kb, v1,
                               make_pdf({"Refunds": "Annual plans are refundable within 60 days."}))
        assert r.status_code == 201, r.text
        v2 = r.json()["id"]

        docs = await _docs(c, h, kb)
        assert docs[v2]["status"] == "ready" and docs[v2]["is_current"] is True
        assert docs[v1]["is_current"] is False and docs[v1]["superseded_at"]
        found = await _search(c, h, kb, "refundable annual")
        assert v2 in found and v1 not in found
