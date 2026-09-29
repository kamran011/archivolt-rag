import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole

MAX_MESSAGES = 5000


class DailyUsage(BaseModel):
    date: str
    answers: int
    abstained: int
    cost_usd: float


class UsageSummary(BaseModel):
    days: int
    total_answers: int
    abstained: int
    abstention_rate: float | None
    total_cost_usd: float
    avg_cost_usd: float | None
    avg_citations: float | None
    conflicts_flagged: int
    agentic_answers: int
    strategy_counts: dict[str, int]
    avg_stage_ms: dict[str, float]
    daily: list[DailyUsage]
    truncated: bool


@dataclass
class UsageRow:
    created_at: datetime
    abstained: bool
    retrieval_metadata: dict | None
    token_usage: dict | None
    citations: list | None


def aggregate_usage(rows: list[UsageRow], days: int, truncated: bool = False) -> UsageSummary:
    """Pure aggregation over assistant messages (kept separate from I/O so it
    can be tested without a database)."""
    total = len(rows)
    abstained = sum(1 for r in rows if r.abstained)

    costs: list[float] = []
    strategies: Counter[str] = Counter()
    stage_totals: dict[str, float] = defaultdict(float)
    stage_counts: dict[str, int] = defaultdict(int)
    daily: dict[str, list[float | int]] = defaultdict(lambda: [0, 0, 0.0])
    conflicts = agentic = 0

    for r in rows:
        meta = r.retrieval_metadata or {}
        cost = float((r.token_usage or {}).get("estimated_cost_usd") or 0.0)
        costs.append(cost)

        if meta.get("strategy"):
            strategies[str(meta["strategy"])] += 1
        if meta.get("agent"):
            agentic += 1
        if meta.get("conflicts"):
            conflicts += 1
        for stage, ms in (meta.get("span_ms") or {}).items():
            if isinstance(ms, int | float):
                stage_totals[stage] += ms
                stage_counts[stage] += 1

        bucket = daily[r.created_at.date().isoformat()]
        bucket[0] += 1
        bucket[1] += 1 if r.abstained else 0
        bucket[2] += cost

    answered = [r for r in rows if not r.abstained]
    return UsageSummary(
        days=days,
        total_answers=total,
        abstained=abstained,
        abstention_rate=round(abstained / total, 4) if total else None,
        total_cost_usd=round(sum(costs), 6),
        avg_cost_usd=round(sum(costs) / total, 6) if total else None,
        avg_citations=(
            round(sum(len(r.citations or []) for r in answered) / len(answered), 2)
            if answered
            else None
        ),
        conflicts_flagged=conflicts,
        agentic_answers=agentic,
        strategy_counts=dict(strategies),
        avg_stage_ms={s: round(stage_totals[s] / stage_counts[s], 2) for s in stage_totals},
        daily=[
            DailyUsage(date=d, answers=int(v[0]), abstained=int(v[1]), cost_usd=round(v[2], 6))
            for d, v in sorted(daily.items())
        ],
        truncated=truncated,
    )


class AnalyticsService:
    async def usage(self, db: AsyncSession, org_id: uuid.UUID, days: int) -> UsageSummary:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.organization_id == org_id,
                Message.role == MessageRole.assistant,
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(MAX_MESSAGES + 1)
        )
        messages = (await db.execute(stmt)).scalars().all()
        truncated = len(messages) > MAX_MESSAGES
        rows = [
            UsageRow(m.created_at, m.abstained, m.retrieval_metadata, m.token_usage, m.citations)
            for m in messages[:MAX_MESSAGES]
        ]
        return aggregate_usage(rows, days, truncated)


analytics_service = AnalyticsService()
