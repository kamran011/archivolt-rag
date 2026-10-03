"""
Retrieval debugger: runs the retrieval half of the RAG pipeline stage by stage
and reports what each stage kept, dropped and why. Does not generate an answer
(the only LLM cost is reranking).
"""

import time
import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.engines.keyword_engine import KeywordRetrievalEngine
from app.domains.retrieval.engines.vector_engine import VectorRetrievalEngine
from app.domains.retrieval.evidence import ContextAssembler, EvidenceFilter, _encoding
from app.domains.retrieval.evidence_gate import EvidenceGate, EvidenceGateResult
from app.domains.retrieval.expansion import expand_with_neighbors
from app.domains.retrieval.query_router import RouteDecision, query_router
from app.domains.retrieval.rrf import reciprocal_rank_fusion
from app.domains.retrieval.schemas import (
    RetrievalFilters,
    RetrievalRequest,
    RetrievalStrategy,
    RetrievedChunk,
)
from app.domains.retrieval.service import retrieval_service
from app.providers.reranker.registry import get_reranker

PREVIEW_CHARS = 240


class DebugRequest(BaseModel):
    query: str
    knowledge_base_ids: list[uuid.UUID]
    strategy: RetrievalStrategy | None = None
    """Force a strategy. When omitted, the adaptive router chooses."""
    top_k: int = 20
    filters: RetrievalFilters | None = None


class DebugChunk(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    preview: str
    score: float
    method: str
    page: int | None = None
    is_current: bool = True
    authority_tier: str = "standard"
    tokens: int | None = None
    verdict: str | None = None
    """Set on stages that filter: 'kept', or why the chunk was dropped."""


class DebugStage(BaseModel):
    name: str
    duration_ms: float
    chunks: list[DebugChunk] = []
    note: str | None = None


class DebugResponse(BaseModel):
    query: str
    route: RouteDecision
    routed: bool
    stages: list[DebugStage]
    gate: EvidenceGateResult
    final_context_chunks: int
    final_context_tokens: int


def _view(c: RetrievedChunk, *, verdict: str | None = None, tokens: int | None = None) -> DebugChunk:
    return DebugChunk(
        chunk_id=c.chunk_id,
        document_id=c.document_id,
        document_title=c.document_title,
        preview=" ".join(c.content.split())[:PREVIEW_CHARS],
        score=round(c.score, 4),
        method=c.retrieval_method,
        page=c.metadata.get("page_number"),
        is_current=c.is_current,
        authority_tier=c.authority_tier,
        tokens=tokens,
        verdict=verdict,
    )


class RetrievalDebugger:
    def __init__(self) -> None:
        self._vector = VectorRetrievalEngine()
        self._keyword = KeywordRetrievalEngine()

    async def run(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        req: DebugRequest,
        scope: AccessScope | None = None,
    ) -> DebugResponse:
        stages: list[DebugStage] = []

        def timed_stage(name: str, start: float, chunks: list[DebugChunk], note: str | None = None):
            stages.append(
                DebugStage(
                    name=name,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    chunks=chunks,
                    note=note,
                )
            )

        routed = req.strategy is None
        route = (
            query_router.route(req.query)
            if routed
            else RouteDecision(strategy=req.strategy, reason="forced by caller")
        )

        # 1. Retrieval. Hybrid is shown as its components plus the fusion so
        # you can see which engine contributed what.
        t = time.perf_counter()
        if route.strategy == "hybrid":
            candidate_k = max(req.top_k * 2, 20)
            embedding_model = settings.EMBEDDING_MODEL
            semantic = await self._vector.search(
                db, org_id, req.query, req.knowledge_base_ids, candidate_k, req.filters,
                embedding_model, scope,
            )
            timed_stage("semantic", t, [_view(c) for c in semantic])
            t = time.perf_counter()
            keyword = await self._keyword.search(
                db, org_id, req.query, req.knowledge_base_ids, candidate_k, req.filters,
                embedding_model, scope,
            )
            timed_stage("keyword", t, [_view(c) for c in keyword])
            t = time.perf_counter()
            candidates = reciprocal_rank_fusion([semantic, keyword])[: req.top_k]
            timed_stage("fusion (RRF)", t, [_view(c) for c in candidates])
        else:
            result = await retrieval_service.retrieve(
                db, org_id,
                RetrievalRequest(
                    query=req.query, knowledge_base_ids=req.knowledge_base_ids,
                    strategy=route.strategy, top_k=req.top_k, filters=req.filters,
                ),
                scope=scope,
            )
            candidates = result.chunks
            note = (
                f"'{route.strategy}' returned nothing; fell back to {result.strategy}"
                if result.strategy != route.strategy
                else None
            )
            timed_stage(result.strategy, t, [_view(c) for c in candidates], note)

        # 2. Rerank
        t = time.perf_counter()
        before = {c.chunk_id: c.score for c in candidates}
        reranked = await get_reranker().rerank(req.query, candidates, top_k=10)
        timed_stage(
            "rerank", t,
            [_view(c, verdict=f"was {before[c.chunk_id]:.3f}") for c in reranked],
            f"{len(candidates)} candidates -> top {len(reranked)}",
        )

        # 3. Filter (score threshold, then near-duplicate removal)
        t = time.perf_counter()
        above = EvidenceFilter.filter_by_score(reranked)
        above_ids = {c.chunk_id for c in above}
        kept = EvidenceFilter.deduplicate(above)
        kept_ids = {c.chunk_id for c in kept}
        verdicts = []
        for c in reranked:
            if c.chunk_id not in above_ids:
                verdicts.append(
                    _view(c, verdict=f"dropped: score below {settings.SCORE_FILTER_THRESHOLD}")
                )
            elif c.chunk_id not in kept_ids:
                verdicts.append(_view(c, verdict="dropped: near-duplicate of a higher-ranked chunk"))
            else:
                verdicts.append(_view(c, verdict="kept"))
        timed_stage("filter", t, verdicts)

        # 4. Evidence gate
        gate = EvidenceGate.evaluate(req.query, kept)

        # 5. Context assembly (only meaningful if the gate passes)
        t = time.perf_counter()
        context_chunks: list[RetrievedChunk] = []
        context_tokens = 0
        if gate.pass_gate:
            pool = kept
            if settings.ENABLE_NEIGHBOR_EXPANSION:
                pool = await expand_with_neighbors(db, org_id, kept, scope=scope)
            context_chunks, context_tokens = ContextAssembler.assemble(pool)
            selected_ids = {c.chunk_id for c in context_chunks}
            timed_stage(
                "context",
                t,
                [
                    _view(
                        c,
                        tokens=len(_encoding.encode(c.content)),
                        verdict="in context" if c.chunk_id in selected_ids
                        else "skipped: exceeds token budget",
                    )
                    for c in pool
                ],
                f"{context_tokens}/{settings.MAX_CONTEXT_TOKENS} tokens",
            )
        else:
            timed_stage("context", t, [], f"skipped: evidence gate failed ({gate.reason})")

        return DebugResponse(
            query=req.query,
            route=route,
            routed=routed,
            stages=stages,
            gate=gate,
            final_context_chunks=len(context_chunks),
            final_context_tokens=context_tokens,
        )


retrieval_debugger = RetrievalDebugger()
