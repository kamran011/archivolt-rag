import time
import uuid

import pytest
from jose import jwt

from app.config import settings


def make_token(sub: str | None = None, exp_delta: int = 3600, secret: str | None = None) -> str:
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "email": "test@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, secret or settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_me_requires_auth_header(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_malformed_token(client):
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_expired_token(client):
    token = make_token(exp_delta=-3600)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_wrong_signature(client):
    token = make_token(secret="wrong-secret")
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_organizations_list_requires_auth(client):
    response = await client.get("/api/v1/organizations/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_organizations_create_requires_auth(client):
    response = await client.post(
        "/api/v1/organizations/", json={"name": "Test Org", "slug": "test-org"}
    )
    assert response.status_code == 401


def make_raw_token(**claims) -> str:
    base = {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 3600}
    payload = {**base, **claims}
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "some-other-service"},  # wrong audience
        {},  # no audience (e.g. an anon/service key style token)
    ],
)
@pytest.mark.asyncio
async def test_token_with_wrong_or_missing_audience_is_rejected(client, claims):
    token = make_raw_token(**claims)
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/verify", json={"access_token": token})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_rejects_non_uuid_subject_with_401_not_500(client):
    token = make_raw_token(aud="authenticated", sub="not-a-uuid")
    r = await client.post("/api/v1/auth/verify", json={"access_token": token})
    assert r.status_code == 401
