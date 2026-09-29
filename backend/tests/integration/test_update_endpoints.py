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
