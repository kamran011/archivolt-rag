import asyncio
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.rag.schemas import RAGRequest
from app.domains.rag.service import rag_service
from app.domains.retrieval.access import AccessScope, Actor
from app.domains.retrieval.schemas import RetrievalRequest, RetrievalStrategy
from app.domains.retrieval.service import retrieval_service
from app.evals import metrics
from app.evals.dataset import EvalCase
from app.evals.report import CaseResult, EvalReport, summarize
from app.models.organization_member import OrgRole

logger = structlog.get_logger()

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def _run_case(
    session_factory: SessionFactory,
    org_id: uuid.UUID,
    kb_ids: list[uuid.UUID],
    case: EvalCase,
    *,
    strategy: RetrievalStrategy,
    k: int,
    agentic: bool,
    model: str,
    retrieval_only: bool,
    mode: str,
    scope: AccessScope,
) -> CaseResult:
    m: dict[str, float | None] = {}
    async with session_factory() as db:
        if not case.should_abstain:
            result = await retrieval_service.retrieve(
                db,
                org_id,
                RetrievalRequest(
                    query=case.question, knowledge_base_ids=kb_ids, strategy=strategy, top_k=k
                ),
                scope=scope,
            )
            chunks = result.chunks
            m["hit_rate"] = metrics.hit_at_k(chunks, case, k)
            m["recall"] = metrics.recall_at_k(chunks, case, k)
            m["precision"] = metrics.precision_at_k(chunks, case, k)
            m["mrr"] = metrics.reciprocal_rank(chunks, case)
            m["ndcg"] = metrics.ndcg_at_k(chunks, case, k)

        if not retrieval_only:
            start = time.perf_counter()
            response = await rag_service.query(
                db,
                org_id,
                RAGRequest(
                    query=case.question, knowledge_base_ids=kb_ids, model=model,
                    agentic=agentic, mode=mode,
                    conversation_history=case.history or None,
                ),
                scope=scope,
                actor=Actor(
                    user_id=scope.user_id,
                    role=OrgRole.admin if scope.is_admin else OrgRole.member,
                ),
            )
            m["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
            m["cost_usd"] = response.retrieval_metadata.get("estimated_cost_usd") or (
                (response.retrieval_metadata.get("agent") or {}).get("planner_cost_usd", 0.0)
            )
            m["abstention_correct"] = 1.0 if response.abstained == case.should_abstain else 0.0
            if not response.abstained:
                m["keyword_coverage"] = metrics.keyword_coverage(
                    response.answer, case.expected_keywords
                )
                m["faithfulness"] = metrics.faithfulness(response.claim_verifications)
            if case.forbidden_documents:
                m["leaked"] = metrics.leaked(
                    response.answer, response.citations, case.forbidden_documents
                )
            if case.canary:
                m["injected"] = metrics.injected(response.answer, case.canary)
    return CaseResult(case_id=case.id, tags=case.tags, metrics=m)


async def run_eval(
    session_factory: SessionFactory,
    org_id: uuid.UUID,
    kb_ids: list[uuid.UUID],
    cases: list[EvalCase],
    *,
    dataset_name: str = "dataset",
    strategy: RetrievalStrategy = "hybrid",
    k: int = 5,
    agentic: bool = False,
    model: str | None = None,
    retrieval_only: bool = False,
    concurrency: int = 2,
    mode: str = "rag",
    scope: AccessScope | None = None,
) -> EvalReport:
    """Runs every case (each in its own DB session) and aggregates a report.
    A failing case is recorded with its error and excluded from averages, so
    one flaky LLM call cannot sink a whole run."""
    model = model or settings.DEFAULT_LLM_MODEL
    # Default is the least-privileged caller (unrestricted documents only), so a run can
    # show whether restricted content leaks; pass an admin scope to evaluate as an admin.
    scope = scope or AccessScope(user_id=None, is_admin=False)
    sem = asyncio.Semaphore(concurrency)

    async def guarded(case: EvalCase) -> CaseResult:
        async with sem:
            try:
                return await _run_case(
                    session_factory, org_id, kb_ids, case,
                    strategy=strategy, k=k, agentic=agentic, model=model,
                    retrieval_only=retrieval_only, mode=mode, scope=scope,
                )
            except Exception as e:
                logger.warning("eval_case_failed", case_id=case.id, error=str(e))
                return CaseResult(case_id=case.id, tags=case.tags, metrics={}, error=str(e)[:300])

    results = await asyncio.gather(*(guarded(c) for c in cases))
    summary = summarize(list(results), {c.id: c.should_abstain for c in cases})
    return EvalReport(
        dataset=dataset_name,
        config={
            "strategy": strategy, "agentic": agentic, "model": model,
            "retrieval_only": retrieval_only, "mode": mode,
            "access": "admin" if scope.is_admin else "restricted",
            "routing": settings.ENABLE_ADAPTIVE_ROUTING,
            "neighbor_expansion": settings.ENABLE_NEIGHBOR_EXPANSION,
        },
        k=k,
        total_cases=len(cases),
        failed_cases=sum(1 for r in results if r.error),
        summary=summary,
        cases=list(results),
    )
