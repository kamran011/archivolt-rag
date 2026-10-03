"""Regression: GET /organizations/ returned no role, so the web UI treated every owner as a
plain member and locked the settings, eval lab and admin toggles."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.integration.test_upload_to_search import DB_URL, env, onboard, token  # noqa: F401

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


async def test_org_list_and_detail_report_the_callers_role_and_member_count(env):  # noqa: F811
    _, orgs = env
    owner, member, outsider = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, _kb = await onboard(c, orgs, owner, f"roles-{uuid.uuid4().hex[:6]}")
        org = h["X-Organization-Id"]
        r = await c.post(
            f"/api/v1/organizations/{org}/members",
            json={"user_id": str(member), "role": "member"},
            headers=h,
        )
        assert r.status_code == 201, r.text

        as_owner = (await c.get("/api/v1/organizations/", headers=token(owner))).json()
        mine = next(o for o in as_owner if o["id"] == org)
        assert mine["role"] == "owner" and mine["member_count"] == 2

        as_member = (await c.get("/api/v1/organizations/", headers=token(member))).json()
        theirs = next(o for o in as_member if o["id"] == org)
        assert theirs["role"] == "member" and theirs["member_count"] == 2

        detail = await c.get(f"/api/v1/organizations/{org}", headers=token(member))
        assert detail.status_code == 200 and detail.json()["role"] == "member"

        # an unrelated user neither sees the org nor can read its detail
        assert await c.get("/api/v1/organizations/", headers=token(outsider)) is not None
        listed = (await c.get("/api/v1/organizations/", headers=token(outsider))).json()
        assert all(o["id"] != org for o in listed)
        denied = await c.get(f"/api/v1/organizations/{org}", headers=token(outsider))
        assert denied.status_code == 403
