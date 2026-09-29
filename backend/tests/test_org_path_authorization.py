"""IDOR: org-management routes take an org id in the URL, but the caller's role is
established from the X-Organization-Id membership. The two must agree — an admin of org A
must not be able to manage org B by putting B's id in the path."""

import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrgRole


def auth(user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(user_id),
            "email": "u@example.com",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if org_id:
        headers["X-Organization-Id"] = str(org_id)
    return headers


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Organization.__table__, OrganizationMember.__table__],
        )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = override
    yield maker
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def make_org(client, user_id, slug) -> uuid.UUID:
    r = await client.post(
        "/api/v1/organizations/", json={"name": slug, "slug": slug}, headers=auth(user_id)
    )
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


@pytest.mark.asyncio
async def test_admin_of_org_a_cannot_manage_org_b(maker):
    alice, bob, carol = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        org_a = await make_org(c, alice, "org-a")
        org_b = await make_org(c, bob, "org-b")
        # Bob adds carol as a normal member of B so there is a member to attack.
        r = await c.post(
            f"/api/v1/organizations/{org_b}/members",
            json={"user_id": str(carol), "role": "member"},
            headers=auth(bob, org_b),
        )
        assert r.status_code == 201, r.text
        carol_member_id = r.json()["id"]

        alice_as_a = auth(alice, org_a)  # alice is owner of A only

        # 1. rename org B
        r = await c.patch(
            f"/api/v1/organizations/{org_b}", json={"name": "pwned"}, headers=alice_as_a
        )
        assert r.status_code in (403, 404), f"update_org crossed tenants: {r.status_code}"

        # 2. add herself (or anyone) to org B as owner
        r = await c.post(
            f"/api/v1/organizations/{org_b}/members",
            json={"user_id": str(alice), "role": "owner"},
            headers=alice_as_a,
        )
        assert r.status_code in (403, 404), f"add_member crossed tenants: {r.status_code}"

        # 3. change a member's role in org B
        r = await c.patch(
            f"/api/v1/organizations/{org_b}/members/{carol_member_id}",
            json={"role": "admin"},
            headers=alice_as_a,
        )
        assert r.status_code in (403, 404), f"update_member_role crossed: {r.status_code}"

        # 4. remove a member from org B
        r = await c.delete(
            f"/api/v1/organizations/{org_b}/members/{carol_member_id}", headers=alice_as_a
        )
        assert r.status_code in (403, 404), f"remove_member crossed tenants: {r.status_code}"

        # 5. read-side routes must not expose org B either
        assert (await c.get(f"/api/v1/organizations/{org_b}", headers=alice_as_a)).status_code in (
            403,
            404,
        )
        assert (
            await c.get(f"/api/v1/organizations/{org_b}/members", headers=alice_as_a)
        ).status_code in (403, 404)

    # Org B is exactly as Bob left it.
    async with maker() as s:
        org = (await s.execute(select(Organization).where(Organization.id == org_b))).scalar_one()
        assert org.name == "org-b"
        members = (
            (
                await s.execute(
                    select(OrganizationMember).where(OrganizationMember.organization_id == org_b)
                )
            )
            .scalars()
            .all()
        )
        roles = {m.user_id: m.role for m in members}
        assert roles == {bob: OrgRole.owner, carol: OrgRole.member}


@pytest.mark.asyncio
async def test_admin_can_still_manage_own_org(maker):
    """The fix must not break legitimate management of one's own org."""
    alice, dave = uuid.uuid4(), uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        org_a = await make_org(c, alice, "org-a2")
        h = auth(alice, org_a)
        r = await c.patch(f"/api/v1/organizations/{org_a}", json={"name": "renamed"}, headers=h)
        assert r.status_code == 200, r.text
        r = await c.post(
            f"/api/v1/organizations/{org_a}/members",
            json={"user_id": str(dave), "role": "member"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        member_id = r.json()["id"]
        r = await c.patch(
            f"/api/v1/organizations/{org_a}/members/{member_id}",
            json={"role": "viewer"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        r = await c.delete(f"/api/v1/organizations/{org_a}/members/{member_id}", headers=h)
        assert r.status_code == 204, r.text
