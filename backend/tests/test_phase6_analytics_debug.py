import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError
from app.domains.analytics.service import UsageRow, aggregate_usage, analytics_service
from app.domains.auth.dependencies import require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.retrieval import debug as debug_module
from app.domains.retrieval.debug import DebugRequest, RetrievalDebugger
from app.domains.retrieval.schemas import RetrievedChunk
from app.models.organization_member import OrgRole
from app.providers.reranker.llm_reranker import LLMReranker


def row(day, abstained=False, cost=0.01, meta=None, citations=None) -> UsageRow:
    return UsageRow(
        created_at=datetime(2026, 9, day, 12, tzinfo=UTC),
        abstained=abstained,
        retrieval_metadata=meta or {},
        token_usage={"estimated_cost_usd": cost},
        citations=citations,
    )


# ── analytics ────────────────────────────────────────────────────────────────

def test_aggregate_usage():
    rows = [
        row(1, meta={"strategy": "hybrid", "span_ms": {"retrieval": 100, "rerank": 200}},
            citations=[{}, {}]),
        row(1, meta={"strategy": "tree", "span_ms": {"retrieval": 300},
                     "conflicts": [{"topic": "x"}]}, citations=[{}], cost=0.03),
        row(2, abstained=True, cost=0.0, meta={"strategy": "hybrid"}),
        row(2, meta={"strategy": "agentic", "agent": {"steps": []}}, cost=0.06),
    ]
    s = aggregate_usage(rows, days=7)
    assert s.total_answers == 4 and s.abstained == 1 and s.abstention_rate == 0.25
    assert s.total_cost_usd == pytest.approx(0.10)
    assert s.avg_cost_usd == pytest.approx(0.025)
    assert s.avg_citations == pytest.approx(1.0)  # (2 + 1 + 0) / 3 answered
    assert s.strategy_counts == {"hybrid": 2, "tree": 1, "agentic": 1}
    assert s.conflicts_flagged == 1 and s.agentic_answers == 1
    assert s.avg_stage_ms == {"retrieval": 200.0, "rerank": 200.0}
    assert [(d.date, d.answers, d.abstained) for d in s.daily] == [
        ("2026-09-01", 2, 0), ("2026-09-02", 2, 1)
    ]
    assert s.daily[0].cost_usd == pytest.approx(0.04)


def test_aggregate_usage_empty_and_tolerates_missing_data():
    s = aggregate_usage([], days=30)
    assert s.total_answers == 0 and s.abstention_rate is None and s.avg_cost_usd is None
    odd = UsageRow(datetime(2026, 9, 1, tzinfo=UTC), False, None, None, None)
    s = aggregate_usage([odd], days=30)
    assert s.total_cost_usd == 0 and s.strategy_counts == {}


@pytest.mark.asyncio
async def test_usage_query_is_org_scoped_and_assistant_only():
    org_id = uuid.uuid4()
    captured = []

    async def execute(stmt):
        captured.append(stmt)
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    await analytics_service.usage(db, org_id, 30)

    sql = str(captured[0].compile(dialect=postgresql.dialect()))
    params = captured[0].compile(dialect=postgresql.dialect()).params
    assert org_id in params.values()
    assert "conversations.organization_id" in sql


@pytest.mark.asyncio
async def test_usage_endpoint_is_admin_only():
    check = require_role(OrgRole.owner, OrgRole.admin)
    member = CurrentUser(id=uuid.uuid4(), email="m@x.io", organization_id=uuid.uuid4(),
                         role=OrgRole.member)
    with pytest.raises(ForbiddenError):
        await check(member)
    admin = member.model_copy(update={"role": OrgRole.admin})
    assert await check(admin) is admin


# ── retrieval debugger ───────────────────────────────────────────────────────

def rc(title, content, score, method="semantic") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), document_title=title,
        content=content, score=score, metadata={"page_number": 2}, retrieval_method=method,
    )


@pytest.mark.asyncio
async def test_debugger_reports_drops_with_reasons_and_budget():
    org_id = uuid.uuid4()
    good = rc("Policy", "refund window is thirty days for all purchases", 0.9)
    dup = rc("Policy copy", "refund window is thirty days for all purchases", 0.8)
    weak = rc("Noise", "unrelated marketing copy about shoes", 0.1)
    big = rc("Big", "word " * 5000, 0.7)

    dbg = RetrievalDebugger()
    dbg._vector = MagicMock(search=AsyncMock(return_value=[good, weak]))
    dbg._keyword = MagicMock(search=AsyncMock(return_value=[dup, big]))

    llm_scores = {"Policy": 0.9, "Policy copy": 0.8, "Noise": 0.1, "Big": 0.7}

    async def fake_rerank(self, query, chunks, top_k):
        # like the real reranker: replaces fused scores with fresh 0-1 relevance scores
        rescored = [c.model_copy(update={"score": llm_scores[c.document_title]}) for c in chunks]
        return sorted(rescored, key=lambda c: c.score, reverse=True)[:top_k]

    with (
        patch.object(LLMReranker, "rerank", new=fake_rerank),
        patch.object(debug_module.settings, "ENABLE_NEIGHBOR_EXPANSION", False),
    ):
        resp = await dbg.run(
            AsyncMock(), org_id,
            DebugRequest(query="how long is the refund window?",
                         knowledge_base_ids=[uuid.uuid4()], strategy="hybrid"),
        )

    assert [s.name for s in resp.stages] == [
        "semantic", "keyword", "fusion (RRF)", "rerank", "filter", "context"
    ]
    dbg._vector.search.assert_awaited_once()
    assert dbg._vector.search.await_args.args[1] == org_id  # tenant scope passed through

    verdicts = {c.document_title: c.verdict for c in resp.stages[4].chunks}
    assert verdicts["Policy"] == "kept"
    assert verdicts["Policy copy"].startswith("dropped: near-duplicate")
    assert verdicts["Noise"].startswith("dropped: score below")

    assert resp.gate.pass_gate is True
    ctx = {c.document_title: c.verdict for c in resp.stages[5].chunks}
    assert ctx["Policy"] == "in context"
    assert ctx["Big"] == "skipped: exceeds token budget"
    assert resp.final_context_chunks == 1
    assert resp.routed is False and resp.route.reason == "forced by caller"


@pytest.mark.asyncio
async def test_debugger_gate_failure_skips_context_and_uses_router():
    dbg = RetrievalDebugger()
    weak = rc("Noise", "nothing relevant", 0.05)

    async def fake_rerank(self, query, chunks, top_k):
        return chunks

    with (
        patch.object(debug_module.retrieval_service, "retrieve",
                     new=AsyncMock(return_value=MagicMock(chunks=[weak], strategy="keyword"))),
        patch.object(LLMReranker, "rerank", new=fake_rerank),
    ):
        resp = await dbg.run(
            AsyncMock(), uuid.uuid4(),
            DebugRequest(query='find "force majeure"', knowledge_base_ids=[uuid.uuid4()]),
        )

    assert resp.routed is True and resp.route.strategy == "keyword"
    assert resp.gate.pass_gate is False
    assert resp.stages[-1].name == "context" and "evidence gate failed" in resp.stages[-1].note
    assert resp.final_context_chunks == 0
