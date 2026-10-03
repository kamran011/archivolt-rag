"""Supabase JWKS key cache for verifying asymmetrically signed access tokens
(ES256 / RS256). Hosted Supabase projects and the local CLI stack sign user
tokens this way; legacy projects use a shared HS256 secret instead."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

CACHE_TTL_S = 600
UNKNOWN_KID_REFETCH_COOLDOWN_S = 30
FETCH_TIMEOUT_S = 5.0


class JWKSUnavailableError(Exception):
    """The key set could not be fetched; callers must fail closed."""


async def _fetch_jwks(url: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
    except (httpx.HTTPError, ValueError) as e:
        raise JWKSUnavailableError(f"could not fetch JWKS from {url}: {e}") from e
    if not isinstance(keys, list):
        raise JWKSUnavailableError("JWKS response has no 'keys' list")
    return keys


class JWKSCache:
    def __init__(self, fetch: Callable[[str], Awaitable[list[dict]]] = _fetch_jwks) -> None:
        self._fetch = fetch
        self._keys: dict[str, dict] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def url() -> str:
        return settings.JWT_JWKS_URL or f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"

    async def get_key(self, kid: str | None) -> dict | None:
        """Returns the JWK for `kid`, or None if the issuer doesn't publish it.
        A kid miss triggers at most one refetch per cooldown window (key
        rotation), so forged kids cannot be used to hammer the auth server."""
        if not kid:
            return None
        now = time.monotonic()
        if kid in self._keys and now - self._fetched_at < CACHE_TTL_S:
            return self._keys[kid]

        async with self._lock:
            now = time.monotonic()
            fresh = now - self._fetched_at < CACHE_TTL_S
            if kid in self._keys and fresh:
                return self._keys[kid]
            cooling = self._fetched_at and now - self._fetched_at < UNKNOWN_KID_REFETCH_COOLDOWN_S
            if kid not in self._keys and cooling:
                return None
            try:
                keys = await self._fetch(self.url())
            except JWKSUnavailableError:
                if kid in self._keys:
                    # Known key, auth server briefly unreachable: keep serving it.
                    logger.warning("jwks_refresh_failed_using_cached_key")
                    return self._keys[kid]
                raise
            self._keys = {k["kid"]: k for k in keys if k.get("kid")}
            self._fetched_at = time.monotonic()
            return self._keys.get(kid)

    def clear(self) -> None:
        self._keys = {}
        self._fetched_at = 0.0


jwks_cache = JWKSCache()
