"""Cache + coordination primitives with a swappable backend (V2).

PostgreSQL stays the source of truth; this is fast, disposable state. `MemoryCache`
(default, per-process) and `RedisCache` (shared) implement the same `Cache` interface, so
callers never import Redis. Every method is best-effort for callers that treat the cache
as an optimisation: wrap use in `safe()` helpers where a cache outage must not fail a
request.
"""

from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager

import structlog

from app.config import settings

logger = structlog.get_logger()


class Cache(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...

    @abstractmethod
    async def delete(self, *keys: str) -> None: ...

    @abstractmethod
    async def sadd(self, set_key: str, member: str, ttl: int | None = None) -> None:
        """Add to a set (used for reverse indexes: document -> cache keys)."""

    @abstractmethod
    async def smembers(self, set_key: str) -> set[str]: ...

    @abstractmethod
    async def incr(self, key: str, ttl: int) -> int:
        """Atomic counter that expires `ttl` seconds after its first increment."""

    @abstractmethod
    async def acquire_lock(self, name: str, ttl: int) -> str | None:
        """Returns an owner token if the lock was taken, else None."""

    @abstractmethod
    async def release_lock(self, name: str, token: str) -> None: ...

    # -- helpers ---------------------------------------------------------------------
    async def get_json(self, key: str):
        raw = await self.get(key)
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value, separators=(",", ":")), ttl)

    async def invalidate_index(self, set_key: str) -> int:
        """Delete every key recorded in a reverse index, then the index itself."""
        members = await self.smembers(set_key)
        if members:
            await self.delete(*members)
        await self.delete(set_key)
        return len(members)

    @asynccontextmanager
    async def lock(self, name: str, ttl: int = 30):
        token = await self.acquire_lock(name, ttl)
        try:
            yield token is not None
        finally:
            if token is not None:
                await self.release_lock(name, token)


class MemoryCache(Cache):
    """Process-local, size-bounded (LRU) with TTLs."""

    def __init__(self, max_entries: int = 10_000, clock: Callable[[], float] = time.monotonic):
        self._data: OrderedDict[str, tuple[str, float | None]] = OrderedDict()
        self._sets: dict[str, tuple[set[str], float | None]] = {}
        self._max = max_entries
        self._clock = clock

    def _expired(self, expires: float | None) -> bool:
        return expires is not None and self._clock() >= expires

    async def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if self._expired(expires):
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key, value, ttl=None):
        self._data[key] = (value, self._clock() + ttl if ttl else None)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def delete(self, *keys):
        for key in keys:
            self._data.pop(key, None)
            self._sets.pop(key, None)

    async def sadd(self, set_key, member, ttl=None):
        members, expires = self._sets.get(set_key, (set(), None))
        if self._expired(expires):
            members, expires = set(), None
        members.add(member)
        if ttl:
            new_expiry = self._clock() + ttl
            expires = new_expiry if expires is None else max(expires, new_expiry)
        self._sets[set_key] = (members, expires)

    async def smembers(self, set_key):
        members, expires = self._sets.get(set_key, (set(), None))
        return set() if self._expired(expires) else set(members)

    async def incr(self, key, ttl):
        item = self._data.get(key)
        if item is None or self._expired(item[1]):
            self._data[key] = ("1", self._clock() + ttl)
            return 1
        count = int(item[0]) + 1
        self._data[key] = (str(count), item[1])
        return count

    async def acquire_lock(self, name, ttl):
        key = f"lock:{name}"
        item = self._data.get(key)
        if item is not None and not self._expired(item[1]):
            return None
        token = uuid.uuid4().hex
        self._data[key] = (token, self._clock() + ttl)
        return token

    async def release_lock(self, name, token):
        key = f"lock:{name}"
        item = self._data.get(key)
        if item is not None and item[0] == token:
            self._data.pop(key, None)


_RELEASE_LOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisCache(Cache):
    def __init__(self, url: str, prefix: str = "ragix:") -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)
        self._p = prefix

    def _k(self, key: str) -> str:
        return self._p + key

    async def get(self, key):
        return await self._r.get(self._k(key))

    async def set(self, key, value, ttl=None):
        await self._r.set(self._k(key), value, ex=ttl)

    async def delete(self, *keys):
        if keys:
            await self._r.delete(*(self._k(k) for k in keys))

    async def sadd(self, set_key, member, ttl=None):
        pipe = self._r.pipeline()
        pipe.sadd(self._k(set_key), member)
        if ttl:
            pipe.expire(self._k(set_key), ttl, gt=True)
        await pipe.execute()

    async def smembers(self, set_key):
        return set(await self._r.smembers(self._k(set_key)))

    async def incr(self, key, ttl):
        pipe = self._r.pipeline()
        pipe.incr(self._k(key))
        pipe.expire(self._k(key), ttl, nx=True)
        count, _ = await pipe.execute()
        return int(count)

    async def acquire_lock(self, name, ttl):
        token = uuid.uuid4().hex
        ok = await self._r.set(self._k(f"lock:{name}"), token, nx=True, ex=ttl)
        return token if ok else None

    async def release_lock(self, name, token):
        await self._r.eval(_RELEASE_LOCK_LUA, 1, self._k(f"lock:{name}"), token)


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        backend = settings.CACHE_BACKEND.lower()
        if backend == "redis":
            _cache = RedisCache(settings.REDIS_URL)
        elif backend == "memory":
            _cache = MemoryCache()
        else:
            raise ValueError(f"Unknown CACHE_BACKEND '{backend}' (expected memory or redis)")
    return _cache


def set_cache(cache: Cache | None) -> None:
    """Swap the process cache (tests)."""
    global _cache
    _cache = cache


async def safe(coro, default=None):
    """Await a cache call; a cache outage degrades to `default`, never fails the request."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001 - any backend failure must degrade, not raise
        logger.warning("cache_unavailable", error=str(e))
        return default
