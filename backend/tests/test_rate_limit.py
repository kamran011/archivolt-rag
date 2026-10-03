import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.exceptions import BudgetExceededError, RateLimitError, register_exception_handlers
from app.core.rate_limit import (
    OrgBudget,
    SlidingWindowLimiter,
    enforce_budget,
    org_budget,
    rate_limit,
)
from app.core.rate_limit import limiter as global_limiter
from app.domains.auth.dependencies import require_org
from app.domains.auth.schemas import CurrentUser
from app.models.organization_member import OrgRole


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_limiter_allows_up_to_limit_then_blocks():
    clock = Clock()
    lim = SlidingWindowLimiter(clock)
    for _ in range(3):
        lim.check("k", 3)
    with pytest.raises(RateLimitError) as exc:
        lim.check("k", 3)
    assert exc.value.retry_after >= 1


def test_limiter_window_slides():
    clock = Clock()
    lim = SlidingWindowLimiter(clock)
    lim.check("k", 1)
    with pytest.raises(RateLimitError):
        lim.check("k", 1)
    clock.t += 61
    lim.check("k", 1)  # old hit aged out


def test_limiter_keys_are_independent_and_zero_disables():
    lim = SlidingWindowLimiter(Clock())
    lim.check("a", 1)
    lim.check("b", 1)  # different key, unaffected
    for _ in range(100):
        lim.check("c", 0)  # 0 = unlimited


def test_budget_blocks_after_cap_and_is_per_org(monkeypatch):
    monkeypatch.setattr(settings, "ORG_DAILY_LLM_BUDGET_USD", 1.0)
    b = OrgBudget(today=lambda: "2026-01-01")
    b.check("org1")
    b.record("org1", 0.6)
    b.check("org1")
    b.record("org1", 0.5)
    with pytest.raises(BudgetExceededError):
        b.check("org1")
    b.check("org2")  # other org unaffected


def test_budget_resets_next_day_and_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ORG_DAILY_LLM_BUDGET_USD", 1.0)
    day = {"d": "2026-01-01"}
    b = OrgBudget(today=lambda: day["d"])
    b.record("o", 5.0)
    with pytest.raises(BudgetExceededError):
        b.check("o")
    day["d"] = "2026-01-02"
    b.check("o")

    monkeypatch.setattr(settings, "ORG_DAILY_LLM_BUDGET_USD", 0.0)
    day["d"] = "2026-01-01"
    b.check("o")  # cap of 0 means unlimited


def test_budget_ignores_missing_or_negative_cost():
    b = OrgBudget(today=lambda: "d")
    b.record("o", None)
    b.record("o", -3)
    assert b.spent_today("o") == 0.0


# --- through real routes ---------------------------------------------------------


def make_app() -> tuple[FastAPI, dict]:
    app = FastAPI()
    register_exception_handlers(app)
    org, user = uuid.uuid4(), uuid.uuid4()
    who = {"org": org, "user": user}

    async def fake_user():
        return CurrentUser(
            id=who["user"], email="e@x.com", organization_id=who["org"], role=OrgRole.member
        )

    app.dependency_overrides[require_org] = fake_user

    @app.get("/limited", dependencies=[Depends(rate_limit("t", "RATE_LIMIT_CHAT_PER_MIN"))])
    async def limited():
        return {"ok": True}

    @app.get("/budgeted", dependencies=[Depends(enforce_budget)])
    async def budgeted():
        return {"ok": True}

    return app, who


@pytest.fixture(autouse=True)
def clean_state():
    global_limiter.reset()
    org_budget.reset()
    yield
    global_limiter.reset()
    org_budget.reset()


@pytest.mark.asyncio
async def test_route_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_CHAT_PER_MIN", 2)
    app, who = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/limited")).status_code == 200
        assert (await c.get("/limited")).status_code == 200
        r = await c.get("/limited")
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

        # A different user in the same org has their own budget of requests.
        who["user"] = uuid.uuid4()
        assert (await c.get("/limited")).status_code == 200


@pytest.mark.asyncio
async def test_route_returns_429_when_org_budget_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "ORG_DAILY_LLM_BUDGET_USD", 0.50)
    app, who = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/budgeted")).status_code == 200
        org_budget.record(who["org"], 0.75)
        r = await c.get("/budgeted")
        assert r.status_code == 429
        assert "budget" in r.json()["detail"].lower()
