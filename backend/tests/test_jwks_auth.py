"""Asymmetric (ES256/JWKS) access-token verification — what real Supabase Auth issues."""

import base64
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk, jwt

from app.config import settings
from app.core import jwks as jwks_module
from app.core.exceptions import UnauthorizedError
from app.core.jwks import JWKSCache, JWKSUnavailableError
from app.domains.auth import dependencies


def make_keypair(kid: str):
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_jwk = {**jwk.construct(public_pem, "ES256").to_dict(), "kid": kid, "alg": "ES256"}
    return private_pem, public_jwk


def claims(**over):
    base = {
        "sub": str(uuid.uuid4()),
        "email": "u@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    return {**base, **over}


def sign(private_pem: str, kid: str | None = "k1", **over) -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims(**over), private_pem, algorithm="ES256", headers=headers)


class FakeFetch:
    def __init__(self, keys: list[dict]):
        self.keys = keys
        self.calls = 0
        self.fail = False

    async def __call__(self, url: str) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise JWKSUnavailableError("down")
        return self.keys


@pytest.fixture
def key():
    return make_keypair("k1")


@pytest.fixture
def jwks(monkeypatch, key):
    fetch = FakeFetch([key[1]])
    cache = JWKSCache(fetch=fetch)
    monkeypatch.setattr(dependencies, "jwks_cache", cache)
    cache.fetch = fetch
    return cache


@pytest.mark.asyncio
async def test_valid_es256_token_is_accepted(jwks, key):
    sub = str(uuid.uuid4())
    user_id, email = await dependencies.decode_access_token(sign(key[0], sub=sub))
    assert str(user_id) == sub and email == "u@example.com"


@pytest.mark.asyncio
async def test_token_signed_by_unpublished_key_is_rejected(jwks):
    other_private, _ = make_keypair("k1")  # same kid, different key material
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(other_private, kid="k1"))


@pytest.mark.asyncio
async def test_unknown_kid_is_rejected(jwks, key):
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(key[0], kid="nope"))


@pytest.mark.asyncio
async def test_missing_kid_is_rejected(jwks, key):
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(key[0], kid=None))


@pytest.mark.asyncio
async def test_expired_and_wrong_audience_are_rejected(jwks, key):
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(key[0], exp=int(time.time()) - 10))
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(key[0], aud="anon"))


@pytest.mark.asyncio
async def test_hs256_token_signed_with_public_key_is_rejected(jwks, key, monkeypatch):
    """Classic alg-confusion: attacker HMAC-signs using the (public) JWKS key bytes."""
    monkeypatch.setattr(settings, "JWT_SECRET", "real-shared-secret-value-123456789")
    public_material = json.dumps(key[1])
    forged = jwt.encode(claims(), public_material, algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(forged)


@pytest.mark.asyncio
async def test_alg_none_is_rejected(jwks):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims())}."
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(unsigned)


@pytest.mark.asyncio
async def test_legacy_hs256_still_works_when_secret_configured(jwks, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", "legacy-secret-value-123456789012345")
    token = jwt.encode(claims(), settings.JWT_SECRET, algorithm="HS256")
    user_id, _ = await dependencies.decode_access_token(token)
    assert user_id


@pytest.mark.asyncio
async def test_hs256_rejected_when_no_secret_configured(jwks, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", "")
    token = jwt.encode(claims(), "anything", algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(token)


@pytest.mark.asyncio
async def test_jwks_outage_fails_closed_as_401_not_500(monkeypatch, key):
    fetch = FakeFetch([key[1]])
    fetch.fail = True
    monkeypatch.setattr(dependencies, "jwks_cache", JWKSCache(fetch=fetch))
    with pytest.raises(UnauthorizedError):
        await dependencies.decode_access_token(sign(key[0]))


@pytest.mark.asyncio
async def test_cached_key_survives_refresh_outage(monkeypatch, key):
    fetch = FakeFetch([key[1]])
    cache = JWKSCache(fetch=fetch)
    monkeypatch.setattr(dependencies, "jwks_cache", cache)
    await dependencies.decode_access_token(sign(key[0]))  # warms the cache
    cache._fetched_at -= jwks_module.CACHE_TTL_S + 1  # expire it
    fetch.fail = True
    user_id, _ = await dependencies.decode_access_token(sign(key[0]))
    assert user_id


@pytest.mark.asyncio
async def test_jwks_is_cached_and_forged_kids_cannot_hammer_the_auth_server(jwks, key):
    await dependencies.decode_access_token(sign(key[0]))
    await dependencies.decode_access_token(sign(key[0]))
    assert jwks.fetch.calls == 1  # second valid token served from cache

    for i in range(20):
        with pytest.raises(UnauthorizedError):
            await dependencies.decode_access_token(sign(key[0], kid=f"forged-{i}"))
    assert jwks.fetch.calls == 1  # cooldown: no refetch storm


@pytest.mark.asyncio
async def test_key_rotation_is_picked_up_after_cooldown(monkeypatch, key):
    new_private, new_jwk = make_keypair("k2")
    fetch = FakeFetch([key[1]])
    cache = JWKSCache(fetch=fetch)
    monkeypatch.setattr(dependencies, "jwks_cache", cache)
    await dependencies.decode_access_token(sign(key[0]))

    fetch.keys = [key[1], new_jwk]
    cache._fetched_at -= jwks_module.UNKNOWN_KID_REFETCH_COOLDOWN_S + 1
    user_id, _ = await dependencies.decode_access_token(sign(new_private, kid="k2"))
    assert user_id and fetch.calls == 2


@pytest.mark.asyncio
async def test_me_endpoint_accepts_es256_token(client, jwks, key):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {sign(key[0])}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "u@example.com"
