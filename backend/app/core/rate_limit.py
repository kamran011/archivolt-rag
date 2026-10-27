"""In-process sliding-window rate limiting and a per-org daily spend cap.

Default is simple and in-process: state lives in the worker process, so with N workers the
effective limit is up to N times higher and everything resets on restart. With
CACHE_BACKEND=redis the per-user limits use a shared fixed-window counter instead (see
`check_shared`), so the limit holds across workers. Durable spend tracking belongs in
the usage ledger (see plan, stage B); this cap is a safety net, not accounting.
"""

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends

from app.config import settings
from app.core.exceptions import BudgetExceededError, RateLimitError
from app.domains.auth.dependencies import require_org
from app.domains.auth.schemas import CurrentUser


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> None:
        """Record a hit; raise RateLimitError if `limit` hits already happened in the
        window. limit <= 0 disables limiting."""
        if limit <= 0:
            return
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = math.ceil(window_seconds - (now - hits[0]))
                raise RateLimitError("Too many requests. Please slow down.", retry_after)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class OrgBudget:
    """Estimated LLM spend per org per UTC day."""

    def __init__(self, today: Callable[[], str] | None = None) -> None:
        self._today = today or (lambda: datetime.now(UTC).strftime("%Y-%m-%d"))
        self._spend: dict[tuple[str, str], float] = defaultdict(float)
        self._lock = threading.Lock()

    def record(self, org_id: object, cost_usd: float | None) -> None:
        if not cost_usd or cost_usd <= 0:
            return
        with self._lock:
            self._spend[(str(org_id), self._today())] += cost_usd

    def spent_today(self, org_id: object) -> float:
        return self._spend.get((str(org_id), self._today()), 0.0)

    def check(self, org_id: object) -> None:
        cap = settings.ORG_DAILY_LLM_BUDGET_USD
        if cap > 0 and self.spent_today(org_id) >= cap:
            raise BudgetExceededError(
                "This organization has reached its daily AI usage budget. Try again tomorrow."
            )

    def reset(self) -> None:
        with self._lock:
            self._spend.clear()


async def check_shared(key: str, limit: int, window_seconds: int = 60) -> None:
    """Fixed-window counter in the shared cache. A cache outage fails open: rate limiting
    must not take the API down."""
    if limit <= 0:
        return
    from app.core.cache import get_cache, safe

    count = await safe(get_cache().incr(f"rl:{key}", window_seconds), 0)
    if count > limit:
        raise RateLimitError("Too many requests. Please slow down.", window_seconds)


limiter = SlidingWindowLimiter()
org_budget = OrgBudget()


def rate_limit(name: str, limit_setting: str):
    """Dependency factory: `dependencies=[Depends(rate_limit("chat", "RATE_LIMIT_CHAT_PER_MIN"))]`.
    The limit is read from settings on every request so it can be tuned without restarts
    of the code path (and patched in tests)."""

    async def dependency(current_user: CurrentUser = Depends(require_org)) -> None:
        key = f"{name}:{current_user.organization_id}:{current_user.id}"
        limit = getattr(settings, limit_setting)
        if settings.CACHE_BACKEND.lower() == "redis":
            await check_shared(key, limit)
        else:
            limiter.check(key, limit)

    return dependency


async def enforce_budget(current_user: CurrentUser = Depends(require_org)) -> None:
    org_budget.check(current_user.organization_id)
