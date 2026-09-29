"""Every PATCH endpoint against real Postgres. Regression: updated_at is DB-generated
(onupdate=now()) and was left expired after UPDATE, so serializing the response raised
and every PATCH returned 500."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    token,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


async def test_patch_endpoints_return_200(env):  # noqa: F811
    _, orgs = env
    owner = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, owner, f"patch-{uuid.uuid4().hex[:6]}")
        org = h["X-Organization-Id"]

        r = await c.patch(f"/api/v1/organizations/{org}", json={"name": "Renamed"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Renamed" and r.json()["updated_at"]

        r = await c.patch(
            f"/api/v1/knowledge-bases/{kb}", json={"description": "updated"}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["description"] == "updated"

        doc = await upload(c, h, kb, "p.pdf", make_pdf({"T": "policy text"}))
        r = await c.patch(
            f"/api/v1/knowledge-bases/{kb}/documents/{doc}",
            json={"authority_tier": "authoritative"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["authority_tier"] == "authoritative"

        other = uuid.uuid4()
        r = await c.post(
            f"/api/v1/organizations/{org}/members",
            json={"user_id": str(other), "role": "member"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        member_id = r.json()["id"]
        r = await c.patch(
            f"/api/v1/organizations/{org}/members/{member_id}", json={"role": "viewer"}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "viewer"


async def test_org_admin_cannot_manage_other_org_on_postgres(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h_a, _ = await onboard(c, orgs, uuid.uuid4(), f"idor-a-{uuid.uuid4().hex[:6]}")
        h_b, _ = await onboard(c, orgs, uuid.uuid4(), f"idor-b-{uuid.uuid4().hex[:6]}")
        org_b = h_b["X-Organization-Id"]

        r = await c.patch(f"/api/v1/organizations/{org_b}", json={"name": "pwned"}, headers=h_a)
        assert r.status_code == 404, r.text
        r = await c.post(
            f"/api/v1/organizations/{org_b}/members",
            json={"user_id": str(uuid.uuid4()), "role": "owner"},
            headers=h_a,
        )
        assert r.status_code == 404, r.text


async def test_document_inspection_endpoints_and_isolation(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"insp-{uuid.uuid4().hex[:6]}")
        doc = await upload(
            c, h, kb, "p.pdf",
            make_pdf({"Refund Policy": "Annual plans are refundable within 30 days."}),
        )
        base = f"/api/v1/knowledge-bases/{kb}/documents/{doc}"

        r = await c.get(f"{base}/chunks", headers=h)
        assert r.status_code == 200, r.text
        page = r.json()
        assert page["total"] >= 1 and page["items"][0]["has_embedding"] is True
        assert "embedding" not in page["items"][0]  # vectors are never sent
        assert "refund" in page["items"][0]["content"].lower()

        r = await c.get(f"{base}/chunks", params={"limit": 1, "offset": 999}, headers=h)
        assert r.json()["items"] == [] and r.json()["total"] == page["total"]

        r = await c.get(f"{base}/tree", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["document_id"] == doc and isinstance(r.json()["nodes"], list)

        # Another org cannot inspect this document's chunks or tree.
        h2, kb2 = await onboard(c, orgs, uuid.uuid4(), f"insp2-{uuid.uuid4().hex[:6]}")
        other = f"/api/v1/knowledge-bases/{kb2}/documents/{doc}"
        assert (await c.get(f"{other}/chunks", headers=h2)).status_code == 404
        assert (await c.get(f"{other}/tree", headers=h2)).status_code == 404


async def test_image_upload_ingests_via_ocr_and_is_searchable(env, monkeypatch):  # noqa: F811
    import pymupdf as fitz

    from app.config import settings
    from app.domains.ingestion.parsers import image_parser as image_parser_module
    from app.providers.ocr.base import OCRProvider, OCRResult

    class FakeOCR(OCRProvider):
        async def read(self, image_png):
            return OCRResult(text="# Receipt\n\nRefund issued: 45 EUR to customer zebra", model="v")

    monkeypatch.setattr(settings, "ENABLE_VISION_INGESTION", True)
    monkeypatch.setattr(image_parser_module, "get_ocr_provider", lambda: FakeOCR())
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), False)
    pix.clear_with(180)
    png = pix.tobytes("png")

    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"img-{uuid.uuid4().hex[:6]}")
        r = await c.post(
            f"/api/v1/knowledge-bases/{kb}/documents/upload",
            files={"file": ("receipt.png", png, "image/png")},
            headers=h,
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc["file_type"] == "image"
        got = (await c.get(f"/api/v1/knowledge-bases/{kb}/documents/{doc['id']}", headers=h)).json()
        assert got["status"] == "ready", got
        assert got["parsing_metadata"]["vision_calls"] == 1

        r = await c.post(
            "/api/v1/retrieval/search",
            json={"query": "refund zebra", "knowledge_base_ids": [kb], "strategy": "keyword"},
            headers=h,
        )
        chunk = r.json()["chunks"][0]
        assert "zebra" in chunk["content"]
        assert "vision_ocr" in chunk["metadata"].get("derived_from", [])

        # A file that only claims to be an image is rejected at upload.
        r = await c.post(
            f"/api/v1/knowledge-bases/{kb}/documents/upload",
            files={"file": ("evil.png", b"<svg onload=alert(1)>", "image/png")},
            headers=h,
        )
        assert r.status_code == 422, r.text
